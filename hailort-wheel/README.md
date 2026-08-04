# hailort-wheel/

Place the HailoRT Python wheel you downloaded from the
[Hailo Developer Zone](https://hailo.ai/developer-zone/) here (e.g.
`hailort-4.x.y-cp313-cp313-linux_x86_64.whl`) before building
[`Dockerfile.hailo`](../Dockerfile.hailo). It is account-gated and not on public
PyPI, so it cannot be fetched automatically - see the header comment in
`Dockerfile.hailo` for details. `.whl` files placed here are git-ignored; do not
commit vendor-distributed binaries into this repository.
