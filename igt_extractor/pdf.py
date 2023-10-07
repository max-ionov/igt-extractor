import pdfminer
import pdfminer.high_level
from pdfminer.layout import LTTextContainer, LTChar, LTAnno
import collections
import palaso.teckit


def avg_fontsize(page):
    size = collections.Counter()
    for line in page:
        size.update(word['size'] for word in line)
    return size.most_common(1)[0][0]


def remove_header_footer(page):
    start = 0
    end = len(page) - 1

    avg_size = avg_fontsize(page)

    for i, line in enumerate(page):
        if collections.Counter(word['size'] for word in line).most_common(1)[0][0] == avg_size:
            start = i
            break

    for i, line in enumerate(page[::-1]):
        if collections.Counter(word['size'] for word in line).most_common(1)[0][0] == avg_size:
            end = len(page) - i
            break

    return page[start:end], start, end


def read_mapping(filename: str):
    with open(filename, 'rb') as map_file:
        mapping = palaso.teckit.compiler.compile(map_file.read())
    return palaso.teckit.engine.Converter(mapping, forward=True)


def inside(elem_bbox: tuple[float, float, float, float], page_box: tuple[float, float, float, float]):
    return (elem_bbox[0] >= page_box[0] and
            elem_bbox[1] >= page_box[1] and
            elem_bbox[2] <= page_box[2] and
            elem_bbox[3] <= page_box[3])


class PDFText:
    def __init__(self,
                 filename: str,
                 bounding_box: tuple[float, float, float, float] | None = None,
                 font_mappings: dict[str, str] | None = None,
                 code_page: str = 'cp1252',
                 main_language: str = 'en'):
        self.filename = filename
        self.pages = None
        self.text = None
        self.process_file(filename, bounding_box, font_mappings, code_page, main_language)

    def _get_mapping(self, char: str, font: str):
        encoder = None
        for key, val in self.encoders.items():
            if key in font:
                encoder = val

        if not encoder:
            return char

        if char.startswith('(cid:'):
            char = chr(int(char.replace('(cid:', '').rstrip(')')))
        encoder.flush()
        encoder.convert(char.encode(self.code_page, errors='replace'))
        res = encoder.flush()
        return res

    def _extract_text_from_line(self, line: LTTextContainer):
        fonts = collections.Counter()
        sizes = collections.Counter()
        text = ''

        tokens = []

        for char in line:
            if isinstance(char, LTChar):
                text += self._get_mapping(char.get_text(), char.fontname)
                fonts[char.fontname] += 1
                sizes[round(char.size, 2)] += 1

            # sometimes there is an LTAnno that actually separates different words
            if isinstance(char, LTAnno) and char.get_text() == ' ':
                tokens.append({'text': text,
                               'font': fonts.most_common(1)[0][0],
                               'size': sizes.most_common(1)[0][0]})
                fonts = collections.Counter()
                sizes = collections.Counter()
                text = ''

        if text:
            tokens.append({'text': text,
                           'font': fonts.most_common(1)[0][0],
                           'size': sizes.most_common(1)[0][0]})

        return tokens

    def _set_properties(self,
                        bounding_box: tuple[float, float, float, float] | None,
                        font_mappings: dict[str, str] | None,
                        code_page: str,
                        main_language: str):
        self.bounding_box = bounding_box
        self.code_page = code_page
        self.main_language = main_language

        self.encoders = {key: read_mapping(val) for key, val in font_mappings.items()} if font_mappings else {}

    def process_file(self,
                     filename: str,
                     bounding_box: tuple[float, float, float, float] | None = None,
                     font_mappings: dict[str, str] | None = None,
                     code_page: str = 'cp1252',
                     main_language: str = 'en'):
        self.pages = []
        self._set_properties(bounding_box, font_mappings, code_page, main_language)

        for page in pdfminer.high_level.extract_pages(filename):
            lines = collections.defaultdict(list)
            for elem in page:
                for line in elem if isinstance(elem, LTTextContainer) else [elem]:
                    if isinstance(line, LTTextContainer):
                        if self.bounding_box and not inside(line.bbox, bounding_box):
                            continue
                        lines[line.y1].extend(self._extract_text_from_line(line))
            self.pages.append([lines[coord] for coord in sorted(lines, reverse=True)])

    def extract_text(self, remove_headers=True):
        self.text = []
        for i, page in enumerate(self.pages):
            if not page:
                continue
            for j, line in enumerate(remove_header_footer(page)[0] if remove_headers else page):
                self.text.append({'text': '\t'.join(word['text'] for word in line), 'page': i, 'line': j})

        return self.text
