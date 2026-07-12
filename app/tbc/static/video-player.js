(() => {
  const PTZ_STOP_ON_RELEASE = "Stop";

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
      this._seeking = false;
      this._ptzActive = null;
      this._buildShell();
      this._buildBar();
      if (options.ptz) this._buildPtzOverlay(options.ptz);
      this._wireVideoEvents();
      if (options.src) this.load(options.src);
    }

    load(src) {
      this._teardownHls();
      const video = this.video;
      const isHls = /\.m3u8(\?|$)/.test(src);
      video.dataset.tbcSrc = src;
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

    destroy() {
      this._teardownHls();
      this._clearPtzHold();
    }

    _teardownHls() {
      if (this.hls) {
        this.hls.destroy();
        this.hls = null;
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
      playButton.setAttribute("aria-label", "Wiedergabe/Pause");
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
      muteButton.setAttribute("aria-label", "Stumm");
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
      fullscreenButton.setAttribute("aria-label", "Vollbild");
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
        <button type="button" class="tbc-ptz-btn tbc-ptz-up" data-ptz="Up" aria-label="Hoch">▲</button>
        <button type="button" class="tbc-ptz-btn tbc-ptz-left" data-ptz="Left" aria-label="Links">◄</button>
        <button type="button" class="tbc-ptz-btn tbc-ptz-stop" data-ptz="Stop" aria-label="Stopp">■</button>
        <button type="button" class="tbc-ptz-btn tbc-ptz-right" data-ptz="Right" aria-label="Rechts">►</button>
        <button type="button" class="tbc-ptz-btn tbc-ptz-down" data-ptz="Down" aria-label="Runter">▼</button>
      `;
      overlay.appendChild(pad);

      const zoom = document.createElement("div");
      zoom.className = "tbc-ptz-zoom";
      zoom.innerHTML = `
        <button type="button" class="tbc-ptz-btn" data-ptz="ZoomDec" aria-label="Auszoomen">－</button>
        <button type="button" class="tbc-ptz-btn" data-ptz="ZoomInc" aria-label="Einzoomen">＋</button>
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
