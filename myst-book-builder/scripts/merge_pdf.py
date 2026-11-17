"""逐原分件解釋目的地，再合併並重開核驗；不猜測其他 origin 的連結。"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse
from browser_cdp import sha, write_json


def scalar(value):
    from pypdf.generic import NullObject
    if isinstance(value, NullObject):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


def navigation(writer, readers, mapping, offsets, origin):
    """核心改寫自原分件先解名稱流程；分類以清單的精確 origin 為準。"""
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, IndirectObject
    slugs = {m['slug']: i for i, m in enumerate(mapping)}
    slugs.update({m['html']: i for i, m in enumerate(mapping)})
    slugs['index.html'] = slugs['']
    destinations = [r.named_destinations for r in readers]
    lookups = [{(p.indirect_reference.idnum, p.indirect_reference.generation): j for j, p in enumerate(r.pages)} for r in readers]
    plans, unresolved, preserved = [], [], []

    def resolve(part, value):
        reader = readers[part]
        if isinstance(value, (str, bytes)):
            name = value.decode() if isinstance(value, bytes) else str(value)
            candidates = [name, '/' + unquote(name).lstrip('/'), unquote(name).lstrip('/')]
            destination = next((destinations[part][k] for k in candidates if k in destinations[part]), None)
            if destination is None:
                raise ValueError('原分件缺少命名目的地：' + name)
            page = reader.get_destination_page_number(destination)
            tail = list(destination.dest_array[1:])
        else:
            arr = value.get_object() if hasattr(value, 'get_object') else value
            if not isinstance(arr, (list, tuple)) or len(arr) < 2:
                raise ValueError('無效目的地陣列')
            reference = arr[0]
            page = lookups[part][(reference.idnum, reference.generation)] if isinstance(reference, IndirectObject) else int(reference)
            tail = list(arr[1:])
        if page is None or not 0 <= page < len(reader.pages):
            raise ValueError('目的地頁碼越界')
        # /XYZ、/FitH 等座標值必須在原目的頁範圍，Null 表示保留檢視位置。
        kind = str(tail[0])
        coords = [scalar(v) for v in tail[1:]]
        box = reader.pages[page].mediabox
        if kind == '/XYZ':
            if len(coords) != 3 or (coords[0] is not None and not float(box.left)-1 <= coords[0] <= float(box.right)+1) or (coords[1] is not None and not float(box.bottom)-1 <= coords[1] <= float(box.top)+1):
                raise ValueError('XYZ 座標越界')
        return offsets[part] + page, tail

    for part, reader in enumerate(readers):
        for page_number, page in enumerate(reader.pages):
            for annotation_number, ref in enumerate(page.get('/Annots', [])):
                annot = ref.get_object()
                action = annot.get('/A')
                action = action.get_object() if action else {}
                value, uri = annot.get('/Dest'), None
                if value is None and action.get('/S') == '/GoTo':
                    value = action['/D']
                elif value is None and action.get('/S') == '/URI':
                    uri = str(action['/URI'])
                    parsed = urlparse(uri)
                    actual_origin = f'{parsed.scheme}://{parsed.netloc}'
                    if actual_origin != origin:
                        preserved.append(dict(page=offsets[part]+page_number+1, annotation=annotation_number, uri=uri,
                                              category='other_localhost' if parsed.hostname in ('localhost', '127.0.0.1', '::1') else 'external'))
                        continue
                elif value is None:
                    continue
                try:
                    if uri is not None:
                        path = unquote(parsed.path).strip('/')
                        if path.endswith('/index.html'):
                            path = path[:-11]
                        target = slugs[path]
                        if parsed.fragment:
                            target_page, tail = resolve(target, unquote(parsed.fragment))
                        else:
                            target_page, tail = offsets[target], [NameObject('/Fit')]
                    else:
                        target_page, tail = resolve(part, value)
                    plans.append(dict(source_part=part, page=offsets[part]+page_number, annotation=annotation_number,
                                      target_page=target_page, tail=tail, original_uri=uri))
                except (KeyError, ValueError, TypeError) as exc:
                    unresolved.append(dict(part=part, page=page_number+1, annotation=annotation_number, uri=uri, error=str(exc)))
    report = dict(unresolved=unresolved, preserved_uris=preserved, links=[dict(page=p['page']+1, annotation=p['annotation'], source_part=p['source_part'],
                      target_page=p['target_page']+1, coordinates=[scalar(v) for v in p['tail']], original_uri=p['original_uri']) for p in plans])
    if unresolved:
        return report
    for plan in plans:
        annot = writer.pages[plan['page']]['/Annots'][plan['annotation']].get_object()
        dest = ArrayObject([writer.pages[plan['target_page']].indirect_reference,
                            *[v.clone(writer) if hasattr(v, 'clone') else v for v in plan['tail']]])
        annot[NameObject('/A')] = DictionaryObject({NameObject('/S'): NameObject('/GoTo'), NameObject('/D'): dest})
        annot.pop('/Dest', None)
    names = writer.root_object.get('/Names')
    if names:
        names = names.get_object()
        names.pop('/Dests', None)
        if not names:
            writer.root_object.pop('/Names', None)
    writer.root_object.pop('/Dests', None)
    return report


def verify_navigation(reader, report):
    pages = {(p.indirect_reference.idnum, p.indirect_reference.generation): i for i, p in enumerate(reader.pages)}
    for plan in report['links']:
        annot = reader.pages[plan['page']-1]['/Annots'][plan['annotation']].get_object()
        action = annot['/A'].get_object()
        if action['/S'] != '/GoTo':
            raise ValueError('輸出目的地不是 GoTo')
        dest = action['/D']
        if pages[(dest[0].idnum, dest[0].generation)] != plan['target_page']-1 or [scalar(v) for v in dest[1:]] != plan['coordinates']:
            raise ValueError('輸出目的地頁碼／座標不符')
    for kept in report['preserved_uris']:
        annot = reader.pages[kept['page']-1]['/Annots'][kept['annotation']].get_object()
        if str(annot['/A']['/URI']) != kept['uri']:
            raise ValueError('外鏈被變更')
    report['verified_targets_and_coordinates'] = len(report['links'])


def content_hash(page):
    content = page.get_contents()
    return hashlib.sha256(content.get_data() if content else b'').hexdigest()


def merge(manifest_path, out, report_path, origin):
    report = dict(success=False, errors=[], script_sha256=sha(__file__))
    temporary = out.with_suffix(out.suffix + '.pending')
    try:
        from pypdf import PdfReader, PdfWriter
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not manifest.get('success') or not manifest.get('complete'):
            raise ValueError('拒絕失敗／不完整的列印清單')
        if origin != manifest.get('print_origin') or urlparse(origin).path not in ('', '/'):
            raise ValueError('--print-origin 與實際列印證據不符')
        evidence_path = Path(manifest['evidence_index'])
        if sha(evidence_path) != manifest['evidence_index_sha256']:
            raise ValueError('列印證據 index SHA 不符')
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        if not evidence.get('success') or evidence['print_origin'] != origin:
            raise ValueError('列印證據狀態／origin 不符')
        mapping = manifest['pages']
        if len({p['slug'] for p in mapping}) != len(mapping):
            raise ValueError('重複 slug')
        if not mapping or [p['slug'] for p in mapping] != [p['slug'] for p in manifest['inputs']['pages']]:
            raise ValueError('清單未完整保留 toc 順序')
        if len(evidence['pages']) != len(mapping):
            raise ValueError('證據頁數不符')
        for page, record, original in zip(mapping, evidence['pages'], manifest['inputs']['pages']):
            if any(page.get(k) != original.get(k) for k in original) or not page.get('source') or not page.get('html_sha256') or not page.get('json_sha256'):
                raise ValueError('頁面映射／來源指紋不符')
            if not record.get('success') or record['slug'] != page['slug'] or record['part_sha256'] != page['part_sha256']:
                raise ValueError('逐頁列印狀態不符')
            if sha(page['part']) != page['part_sha256'] or sha(page['evidence']) != page['evidence_sha256']:
                raise ValueError('part／逐頁證據 SHA 不符')
        readers = [PdfReader(p['part']) for p in mapping]
        writer = PdfWriter()
        offsets, expected_content = [], []
        total = 0
        for page, reader in zip(mapping, readers):
            offsets.append(total)
            writer.append(reader, import_outline=False)
            writer.add_outline_item(page['title'], total)
            expected_content.extend(content_hash(p) for p in reader.pages)
            total += len(reader.pages)
        report['navigation'] = navigation(writer, readers, mapping, offsets, origin)
        if report['navigation']['unresolved']:
            raise ValueError('存在未解析的書內目的地')
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() or temporary.exists():
            raise ValueError('輸出已存在；請保留舊輸出並指定新路徑')
        with temporary.open('wb') as stream:
            writer.write(stream)
        reopened = PdfReader(temporary)
        if len(reopened.pages) != total or len(reopened.outline) != len(mapping):
            raise ValueError('重開後頁數／書籤數不符')
        for item, offset, page in zip(reopened.outline, offsets, mapping):
            if reopened.get_destination_page_number(item) != offset or item.title != page['title']:
                raise ValueError('書籤次序／目標不符')
        if expected_content != [content_hash(p) for p in reopened.pages]:
            raise ValueError('合併變更原 part 內容流')
        verify_navigation(reopened, report['navigation'])
        temporary.rename(out)
        report.update(success=True, pages=total, bookmarks=len(mapping), output_sha256=sha(out),
                      parts=[dict(slug=p['slug'], source=p['source'], part=p['part'], first_page=o+1, pages=len(r.pages), sha256=p['part_sha256']) for p, o, r in zip(mapping, offsets, readers)])
    except Exception as exc:
        report['errors'].append(str(exc))
    write_json(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--print-origin', required=True)
    args = parser.parse_args()
    report = merge(args.manifest, args.out, args.report, args.print_origin)
    print('通過' if report['success'] else '阻斷：' + '; '.join(report['errors']))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
