# Third-Party Notices

This project is MIT-licensed (see [LICENSE](LICENSE)). It includes the following
third-party component, redistributed under its own license:

## BitCrack — `kangaroo/bitcrack.cl`

The OpenCL kernel `kangaroo/bitcrack.cl` (secp256k1 + SHA-256 + RIPEMD-160 for
the GPU brute-force / "lottery" mode) is vendored from **BitCrack**:

- Source: https://github.com/brichard19/BitCrack
- Copyright (c) 2018 Ben Richard
- License: **MIT**

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

Everything else in this repository — the Pollard's Kangaroo engine and its
OpenCL kernel (`kangaroo/gpu_kangaroo.cl`), the GLV/secp256k1 implementation,
all nine cryptanalytic attacks, the analytics pipeline, and the desktop app —
is original work by the author.

The standalone C++ tools **BitCrack** and **keyhunt** are *not* redistributed
here; build them from their upstream repositories if you want them.
