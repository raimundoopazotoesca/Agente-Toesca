import zipfile, os
from tools.noi_tools import WORK_DIR

cdg_path = os.path.join(WORK_DIR, '2603 Control De Gestión Renta Comercial vAgente.xlsx')
with zipfile.ZipFile(cdg_path) as z:
    # Check workbook.xml to find sheet names/IDs
    wb_xml = z.read('xl/workbook.xml').decode('utf-8')

    # Print all sheet refs
    import re
    sheets = re.findall(r'<sheet name="([^"]*)"[^/]*/>', wb_xml)
    print(f"Total sheets: {len(sheets)}")
    for i, s in enumerate(sheets):
        print(f"  sheet{i+1}: {s}")

    # Check if sheet40 exists
    files = z.namelist()
    noi_sheets = [f for f in files if 'sheet4' in f and 'worksheet' in f]
    print("\nSheets with '4' in name:", sorted(noi_sheets))
    print("\nTotal worksheet files:", len([f for f in files if 'worksheets/sheet' in f]))
