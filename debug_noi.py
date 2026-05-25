import zipfile, re, os
from tools.noi_tools import WORK_DIR, _read_shared_strings, _NOI_RCSD_XML, _SHARED_STRINGS

cdg_path = os.path.join(WORK_DIR, '2603 Control De Gestión Renta Comercial vAgente.xlsx')
with zipfile.ZipFile(cdg_path) as z:
    sheet_xml = z.read(_NOI_RCSD_XML).decode('utf-8')
    ss_xml = z.read(_SHARED_STRINGS).decode('utf-8')

ss_dict = _read_shared_strings(ss_xml)

print("=== Rows 280-300 ===")
for row_num in range(280, 302):
    row_m = re.search(r'<row r="' + str(row_num) + r'"[^>]*>(.*?)</row>', sheet_xml, re.DOTALL)
    if not row_m:
        continue
    row_xml = row_m.group(0)
    # Get col C label
    c_m = re.search(r'<c r="C' + str(row_num) + r'"[^>]*>.*?<v>(\d+)</v>', row_xml, re.DOTALL)
    label = ''
    if c_m and 't="s"' in row_xml:
        label = ss_dict.get(int(c_m.group(1)), '')
    print(f'Row {row_num}: {label!r}  raw={row_xml[:120]}')
