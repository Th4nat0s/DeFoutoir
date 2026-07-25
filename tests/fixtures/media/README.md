# Media test fixtures

These eleven media files provide stable RAW, JPEG, and PNG inputs for the
DeFoutoir test suite. The URLs are pinned to exact upstream commits.

The RAW fixtures are metadata-oriented samples and may contain only a reduced
sensor payload. They are suitable for file discovery, hashing, and metadata
tests without making the Git repository unnecessarily large.

## RAW files

Source repository:
[bep/imagemeta](https://github.com/bep/imagemeta/tree/2289fdf83fcd238d86f72e65c588da687c998437/testdata/images)

Upstream license:
[MIT](https://github.com/bep/imagemeta/blob/2289fdf83fcd238d86f72e65c588da687c998437/LICENSE)

| Local file | Upstream file | SHA-256 |
| --- | --- | --- |
| `raw/sample.arw` | [`sample.arw`](https://github.com/bep/imagemeta/blob/2289fdf83fcd238d86f72e65c588da687c998437/testdata/images/sample.arw) | `a188d977540c9121e51ea45df41b1c24bfb80e12ed18d3ece9b45b4db73d5af2` |
| `raw/sample.cr2` | [`sample.cr2`](https://github.com/bep/imagemeta/blob/2289fdf83fcd238d86f72e65c588da687c998437/testdata/images/sample.cr2) | `651f1c9090adbc1d2e8b69b973b89e051b519f0824d7d9d19c47ca4cf521d872` |
| `raw/_MG_3055.dng` | user-provided Canon/Lightroom DNG regression fixture | `0d4188ef0771f5a74bd172781da4be23cac6c1dcc79fa2dbf43f63b8a6fb93a2` |
| `raw/sample.dng` | [`sample.dng`](https://github.com/bep/imagemeta/blob/2289fdf83fcd238d86f72e65c588da687c998437/testdata/images/sample.dng) | `68e5f8554a17106c20525e4c0b8ade17403f906171e8a3d934fbeb426b8ccc05` |
| `raw/sample.nef` | [`sample.nef`](https://github.com/bep/imagemeta/blob/2289fdf83fcd238d86f72e65c588da687c998437/testdata/images/sample.nef) | `d2807a93c95b14226a02c2f3c392fae6209b8bc477dd23818722e794e5c83a81` |
| `raw/jolstravatnet.pef` | [`jølstravatnet.pef`](https://github.com/bep/imagemeta/blob/2289fdf83fcd238d86f72e65c588da687c998437/testdata/images/bep/j%C3%B8lstravatnet.pef) | `de99991add7af41a21aa8b86f9579f27d5544fdb4b40f4e97964d3adf1989d2b` |

## JPEG and PNG files

Source repository:
[python-pillow/Pillow](https://github.com/python-pillow/Pillow/tree/9e282f5d754fe49ede35fde65fd862c6c50d1f9f/Tests/images)

Upstream license:
[MIT-CMU](https://github.com/python-pillow/Pillow/blob/9e282f5d754fe49ede35fde65fd862c6c50d1f9f/LICENSE)

| Local file | Upstream file | SHA-256 |
| --- | --- | --- |
| `jpeg/exif-gps.jpg` | [`exif_gps.jpg`](https://github.com/python-pillow/Pillow/blob/9e282f5d754fe49ede35fde65fd862c6c50d1f9f/Tests/images/exif_gps.jpg) | `360eb3ce66533146584aa66576130c5ab98c763b7c7f51898892e7eaa7dcab49` |
| `jpeg/flower.jpg` | [`flower.jpg`](https://github.com/python-pillow/Pillow/blob/9e282f5d754fe49ede35fde65fd862c6c50d1f9f/Tests/images/flower.jpg) | `8a9d04b92d0de5836c59ede8ae421235488e4031e893e07b1fe7e4b78f6a9901` |
| `jpeg/hopper.jpg` | [`hopper.jpg`](https://github.com/python-pillow/Pillow/blob/9e282f5d754fe49ede35fde65fd862c6c50d1f9f/Tests/images/hopper.jpg) | `ffe89a0ab0e94114e10777e7313d7fa83d634e34ebc2ea7479085cffa504c920` |
| `png/flower-thumbnail.png` | [`flower_thumbnail.png`](https://github.com/python-pillow/Pillow/blob/9e282f5d754fe49ede35fde65fd862c6c50d1f9f/Tests/images/flower_thumbnail.png) | `24bcfb49a911b30cb29f5c375a9407a3e24a6e78383f76ca9eb728487e1021dc` |
| `png/test-card.png` | [`test-card.png`](https://github.com/python-pillow/Pillow/blob/9e282f5d754fe49ede35fde65fd862c6c50d1f9f/Tests/images/test-card.png) | `b4baeb18d77acc45766811978373a2f087eda5fb05b5c0aadc3291f4aa331fa4` |
