(() => {
  const PTZ_STOP_ON_RELEASE = "Stop";
  const t = (key, parameters) => window.tbcI18n.t(key, parameters);

  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
    const total = Math.floor(seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
    const ss = String(s).padStart(2, "0");
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }

  class TBCPlayer {
    constructor(video, options = {}) {
      this.video = video;
      this.options = options;
      this.hls = null;
      this.pc = null;
      this._seeking = false;
      this._ptzActive = null;
      this._buildShell();
      this._buildBar();
      if (options.ptz) this._buildPtzOverlay(options.ptz);
      if (options.detection && options.detection.cameraId) this._buildDetectionOverlay(options.detection);
      this._wireVideoEvents();
      if (options.src) this.load(options.src, options);
    }

    // `loadOptions.transport === "webrtc"` treats `src` as a WHEP signaling
    // URL instead of a media URL (see _loadWebrtc). Any other value falls
    // back to the original HLS/direct-src sniffing so every existing caller
    // that never passes a transport keeps working unchanged.
    load(src, loadOptions = {}) {
      this._teardownHls();
      this._teardownWebrtc();
      const video = this.video;
      video.dataset.tbcSrc = src;
      if (loadOptions.transport === "webrtc") {
        video.dataset.tbcTransport = "webrtc";
        this._loadWebrtc(src);
        return;
      }
      video.dataset.tbcTransport = "hls";
      const isHls = /\.m3u8(\?|$)/.test(src);
      if (isHls && window.Hls && window.Hls.isSupported()) {
        const hls = new window.Hls({ liveSyncDurationCount: 3, maxLiveSyncPlaybackRate: 1.2 });
        this.hls = hls;
        hls.loadSource(src);
        hls.attachMedia(video);
        if (this.options.autoplay) {
          hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
            video.play().catch(() => {});
          });
        }
      } else {
        video.src = src;
        if (this.options.autoplay) video.play().catch(() => {});
      }
    }

    async _loadWebrtc(offerUrl) {
      if (!window.RTCPeerConnection) {
        if (this.options.onWebrtcError) this.options.onWebrtcError(new Error("WebRTC is not supported by this browser"));
        return;
      }
      const video = this.video;
      const pc = new RTCPeerConnection();
      this.pc = pc;
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.ontrack = (event) => {
        if (video.srcObject !== event.streams[0]) {
          video.srcObject = event.streams[0];
          if (this.options.autoplay) video.play().catch(() => {});
        }
      };
      pc.addEventListener("connectionstatechange", () => {
        if (this.pc === pc && this.options.onWebrtcStateChange) {
          this.options.onWebrtcStateChange(pc.connectionState);
        }
      });
      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        // go2rtc's WHEP endpoint answers a single POST with the full SDP - it
        // does not support trickle ICE - so the offer must carry every
        // candidate up front.
        await this._waitForIceGathering(pc);
        if (this.pc !== pc) return;
        const response = await fetch(offerUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/sdp" },
          body: pc.localDescription.sdp,
        });
        if (!response.ok) throw new Error(`WebRTC offer failed with status ${response.status}`);
        const answerSdp = await response.text();
        if (this.pc !== pc) return;
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
      } catch (error) {
        if (this.pc === pc) this._teardownWebrtc();
        if (this.options.onWebrtcError) this.options.onWebrtcError(error);
      }
    }

    _waitForIceGathering(pc) {
      if (pc.iceGatheringState === "complete") return Promise.resolve();
      return new Promise((resolve) => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          pc.removeEventListener("icegatheringstatechange", onChange);
          resolve();
        };
        const onChange = () => {
          if (pc.iceGatheringState === "complete") finish();
        };
        const timer = window.setTimeout(finish, 2000);
        pc.addEventListener("icegatheringstatechange", onChange);
      });
    }

    destroy() {
      this._teardownHls();
      this._teardownWebrtc();
      this._clearPtzHold();
      this._stopDetectionOverlay();
    }

    _teardownHls() {
      if (this.hls) {
        this.hls.destroy();
        this.hls = null;
      }
    }

    _teardownWebrtc() {
      if (this.pc) {
        this.pc.close();
        this.pc = null;
      }
      if (this.video.srcObject) {
        this.video.srcObject = null;
      }
    }

    _buildShell() {
      const video = this.video;
      video.controls = false;
      video.playsInline = true;
      if (this.options.muted) video.muted = true;
      const shell = document.createElement("div");
      shell.className = "tbc-player";
      shell.tabIndex = 0;
      video.parentNode.insertBefore(shell, video);
      shell.appendChild(video);
      this.shell = shell;
    }

    _buildBar() {
      const bar = document.createElement("div");
      bar.className = "tbc-player-bar";

      const playButton = document.createElement("button");
      playButton.type = "button";
      playButton.className = "tbc-player-btn";
      playButton.setAttribute("aria-label", t("player.play_pause"));
      playButton.textContent = "▶";
      playButton.addEventListener("click", () => {
        if (this.video.paused) this.video.play().catch(() => {});
        else this.video.pause();
      });
      bar.appendChild(playButton);
      this.playButton = playButton;

      const muteButton = document.createElement("button");
      muteButton.type = "button";
      muteButton.className = "tbc-player-btn";
      muteButton.setAttribute("aria-label", t("player.mute"));
      muteButton.textContent = this.video.muted ? "🔇" : "🔊";
      muteButton.addEventListener("click", () => {
        this.video.muted = !this.video.muted;
        muteButton.textContent = this.video.muted ? "🔇" : "🔊";
      });
      bar.appendChild(muteButton);

      if (this.options.mode === "live") {
        const pill = document.createElement("span");
        pill.className = "tbc-player-live-pill";
        pill.textContent = "LIVE";
        bar.appendChild(pill);
      } else {
        const seek = document.createElement("input");
        seek.type = "range";
        seek.className = "tbc-player-seek";
        seek.min = "0";
        seek.max = "1000";
        seek.value = "0";
        seek.addEventListener("pointerdown", () => {
          this._seeking = true;
        });
        seek.addEventListener("input", () => {
          const duration = this.video.duration;
          if (Number.isFinite(duration) && duration > 0) {
            this.video.currentTime = (Number(seek.value) / 1000) * duration;
          }
        });
        seek.addEventListener("change", () => {
          this._seeking = false;
        });
        bar.appendChild(seek);
        this.seek = seek;

        const time = document.createElement("span");
        time.className = "tbc-player-time";
        time.textContent = "0:00 / 0:00";
        bar.appendChild(time);
        this.timeLabel = time;
      }

      const fullscreenButton = document.createElement("button");
      fullscreenButton.type = "button";
      fullscreenButton.className = "tbc-player-btn tbc-player-btn-fullscreen";
      fullscreenButton.setAttribute("aria-label", t("player.fullscreen"));
      fullscreenButton.textContent = "⤢";
      fullscreenButton.addEventListener("click", () => {
        const request = this.shell.requestFullscreen || this.shell.webkitRequestFullscreen;
        if (request) request.call(this.shell);
      });
      bar.appendChild(fullscreenButton);

      this.shell.appendChild(bar);
    }

    _buildPtzOverlay(ptz) {
      this.ptz = ptz;
      const overlay = document.createElement("div");
      overlay.className = "tbc-ptz";

      const pad = document.createElement("div");
      pad.className = "tbc-ptz-pad";
      pad.innerHTML = `
        <button type="button" class="tbc-ptz-btn tbc-ptz-up" data-ptz="Up">▲</button>
        <button type="button" class="tbc-ptz-btn tbc-ptz-left" data-ptz="Left">◄</button>
        <button type="button" class="tbc-ptz-btn tbc-ptz-stop" data-ptz="Stop">■</button>
        <button type="button" class="tbc-ptz-btn tbc-ptz-right" data-ptz="Right">►</button>
        <button type="button" class="tbc-ptz-btn tbc-ptz-down" data-ptz="Down">▼</button>
      `;
      [["Up", "player.ptz_up"], ["Left", "player.ptz_left"], ["Stop", "player.ptz_stop"], ["Right", "player.ptz_right"], ["Down", "player.ptz_down"]]
        .forEach(([command, key]) => pad.querySelector(`[data-ptz="${command}"]`)?.setAttribute("aria-label", t(key)));
      overlay.appendChild(pad);

      const zoom = document.createElement("div");
      zoom.className = "tbc-ptz-zoom";
      zoom.innerHTML = `
        <button type="button" class="tbc-ptz-btn" data-ptz="ZoomDec" aria-label="${t("player.zoom_out")}">－</button>
        <button type="button" class="tbc-ptz-btn" data-ptz="ZoomInc" aria-label="${t("player.zoom_in")}">＋</button>
      `;
      overlay.appendChild(zoom);

      overlay.querySelectorAll("[data-ptz]").forEach((button) => {
        const command = button.dataset.ptz;
        if (command === "Stop") {
          button.addEventListener("click", () => this._sendPtz("Stop"));
          return;
        }
        button.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          this._startPtzHold(command);
        });
        button.addEventListener("pointerup", () => this._stopPtzHold());
        button.addEventListener("pointerleave", () => this._stopPtzHold());
        button.addEventListener("pointercancel", () => this._stopPtzHold());
      });

      this.shell.appendChild(overlay);

      const keyMap = {
        ArrowUp: "Up",
        ArrowDown: "Down",
        ArrowLeft: "Left",
        ArrowRight: "Right",
        "+": "ZoomInc",
        "-": "ZoomDec",
      };
      this.shell.addEventListener("keydown", (event) => {
        const command = keyMap[event.key];
        if (!command || event.repeat) return;
        event.preventDefault();
        this._startPtzHold(command);
      });
      this.shell.addEventListener("keyup", (event) => {
        if (!keyMap[event.key]) return;
        event.preventDefault();
        this._stopPtzHold();
      });
      this.shell.addEventListener("blur", () => this._stopPtzHold());
    }

    _buildDetectionOverlay(detection) {
      this.detection = detection;
      const canvas = document.createElement("canvas");
      canvas.className = "tbc-bbox-overlay";
      this.shell.appendChild(canvas);
      this._detectionCanvas = canvas;
      this._lastDetections = [];
      const poll = () => this._pollDetections();
      poll();
      this._detectionTimer = window.setInterval(poll, 1000);
      this._detectionResizeHandler = () => this._drawDetections(this._lastDetections);
      window.addEventListener("resize", this._detectionResizeHandler);
    }

    _stopDetectionOverlay() {
      if (this._detectionTimer) window.clearInterval(this._detectionTimer);
      this._detectionTimer = null;
      if (this._detectionResizeHandler) window.removeEventListener("resize", this._detectionResizeHandler);
      this._detectionResizeHandler = null;
    }

    async _pollDetections() {
      if (!this.detection || !this.detection.cameraId) return;
      try {
        const response = await fetch(`/api/cameras/${this.detection.cameraId}/detections/live`, {
          credentials: "same-origin",
        });
        if (!response.ok) return;
        const data = await response.json();
        this._lastDetections = (data && data.detections) || [];
      } catch (error) {
        return;
      }
      this._drawDetections(this._lastDetections);
    }

    _drawDetections(detections) {
      const canvas = this._detectionCanvas;
      if (!canvas) return;
      const rect = this.shell.getBoundingClientRect();
      canvas.width = rect.width;
      canvas.height = rect.height;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!detections.length || !this.video.videoWidth || !this.video.videoHeight) return;

      const content = this._videoContentRect(rect);
      const styles = getComputedStyle(document.documentElement);
      const color = styles.getPropertyValue("--accent").trim() || "#e3a558";
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.font = "12px sans-serif";
      ctx.textBaseline = "bottom";

      detections.forEach((item) => {
        const [xmin, ymin, xmax, ymax] = item.box;
        const x = content.offsetX + xmin * content.width;
        const y = content.offsetY + ymin * content.height;
        const width = (xmax - xmin) * content.width;
        const height = (ymax - ymin) * content.height;
        ctx.strokeRect(x, y, width, height);
        const label = item.label || item.key;
        const textWidth = ctx.measureText(label).width + 8;
        ctx.fillStyle = color;
        ctx.fillRect(x, Math.max(0, y - 16), textWidth, 16);
        ctx.fillStyle = "#111817";
        ctx.fillText(label, x + 4, Math.max(16, y));
      });
    }

    _videoContentRect(rect) {
      const videoRatio = this.video.videoWidth / this.video.videoHeight;
      const boxRatio = rect.width / rect.height;
      let width = rect.width;
      let height = rect.height;
      let offsetX = 0;
      let offsetY = 0;
      if (videoRatio > boxRatio) {
        height = rect.width / videoRatio;
        offsetY = (rect.height - height) / 2;
      } else {
        width = rect.height * videoRatio;
        offsetX = (rect.width - width) / 2;
      }
      return { width, height, offsetX, offsetY };
    }

    _startPtzHold(command) {
      if (this._ptzActive === command) return;
      this._ptzActive = command;
      this._ptzPulses = 0;
      const loop = async () => {
        while (this._ptzActive === command) {
          this._ptzPulses += 1;
          await this._sendPtz(command);
          if (this._ptzActive !== command) break;
        }
      };
      loop();
    }

    _stopPtzHold() {
      if (!this._ptzActive) return;
      this._ptzActive = null;
      // Each pulse already self-stops server-side after ~0.5s (ContinuousMove,
      // sleep, Stop). Sending our own Stop here races that in-flight pulse: for
      // a plain click (still on the first pulse) it lands almost immediately
      // after the move started, cutting it short before it's visible. Only
      // force a Stop once the hold has run long enough to start a second
      // pulse - i.e. the button is genuinely being held down.
      if (this._ptzPulses > 1) {
        this._sendPtz(PTZ_STOP_ON_RELEASE);
      }
    }

    _clearPtzHold() {
      this._ptzActive = null;
    }

    async _sendPtz(command) {
      if (!this.ptz || !this.ptz.cameraId) return;
      try {
        const response = await fetch(`/cameras/${this.ptz.cameraId}/control/ptz`, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "fetch",
          },
          body: new URLSearchParams({
            command,
            channel: String(this.ptz.channel || 0),
          }),
        });
        const data = await response.json().catch(() => null);
        if (!response.ok || !data || !data.ok) {
          if (this.ptz.onError) this.ptz.onError((data && data.message) || "PTZ-Befehl fehlgeschlagen");
        }
      } catch (error) {
        if (this.ptz.onError) this.ptz.onError("PTZ-Befehl fehlgeschlagen: Netzwerkfehler");
      }
    }

    _wireVideoEvents() {
      const video = this.video;
      video.addEventListener("play", () => {
        this.playButton.textContent = "⏸";
      });
      video.addEventListener("pause", () => {
        this.playButton.textContent = "▶";
      });
      if (this.seek) {
        video.addEventListener("timeupdate", () => {
          if (this._seeking) return;
          const duration = video.duration;
          if (Number.isFinite(duration) && duration > 0) {
            this.seek.value = String((video.currentTime / duration) * 1000);
          }
          this.timeLabel.textContent = `${formatTime(video.currentTime)} / ${formatTime(duration)}`;
        });
        video.addEventListener("loadedmetadata", () => {
          this.timeLabel.textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration)}`;
        });
      }
    }
  }

  window.TBCPlayer = TBCPlayer;
})();
