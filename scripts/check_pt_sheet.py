import zipfile, re
path = "work/2603 Control De Gestión Renta Comercial vAgente.xlsx"
with zipfile.ZipFile(path) as z:
    wb_xml = z.read("xl/workbook.xml").decode("utf-8")
sheets = re.findall(r'name="([^"]+)"', wb_xml)
pt = [s for s in sheets if "PT" in s]
print("PT sheets:", pt)
print("All A&R sheets:", [s for s in sheets if "A&R" in s])
