# Third-party dependency notices

PDF ETL Toolkit is MIT-licensed. Its Python dependencies remain under their own licenses.

| Direct dependency | License identified by the installed distribution |
|---|---|
| Streamlit | Apache-2.0 |
| pypdf | BSD-3-Clause |
| pdfplumber | MIT |
| pypdfium2 | Apache-2.0 OR BSD-3-Clause, plus PDFium dependency licenses |
| Pillow | MIT-CMU |
| openpyxl | MIT |

The official `pypdfium2` wheels contain license texts under the distribution's `licenses/` directory, including platform-specific `BUILD_LICENSES` for PDFium and its bundled components. Those files include notices for PDFium and components such as Abseil, FreeType, ICU, Little CMS, libjpeg-turbo, OpenJPEG, libpng, simdutf, and zlib. Do not remove those license files when redistributing a `pypdfium2` wheel or its PDFium binaries.

This repository does not vendor those binary dependencies. A normal `pip install -r requirements.txt` installs their independently distributed packages and accompanying metadata. Downstream binary redistributors remain responsible for preserving the exact notices shipped with the versions and platform builds they distribute.

Upstream licensing references:

- [pypdfium2 licensing](https://github.com/pypdfium2-team/pypdfium2#licensing)
- [pypdfium2 PDFium build licenses](https://github.com/pypdfium2-team/pypdfium2/tree/main/BUILD_LICENSES)
- [PDFium license](https://pdfium.googlesource.com/pdfium/+/refs/heads/main/LICENSE)
