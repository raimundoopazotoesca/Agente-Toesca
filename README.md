# Agente Toesca — Automatización Microsoft 365

Agente conversacional con Gemini 2.5 Flash para automatizar Outlook, SharePoint y Excel en entorno corporativo.

## Compatibilidad

| Funcionalidad | Windows | Mac |
|---|---|---|
| Excel / SharePoint / archivos | OK | OK |
| Gestión Renta Comercial (xlsx) | OK | OK |
| Precios bursátiles (web) | OK | OK |
| Email (Outlook Desktop) | OK | No disponible |

---

## Instalación en Mac

### 1. Clonar el repositorio

```bash
git clone https://github.com/raimundoopazotoesca/Agente-Toesca.git
cd Agente-Toesca
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> `pywin32` (Windows only) se omite automáticamente en Mac.

### 3. Configurar el `.env`

```bash
cp .env.example .env
```

Editar `.env` con los valores correctos para Mac:

```env
GEMINI_API_KEY=tu_clave_de_google_ai_studio

# Ruta de OneDrive sincronizado en Mac (buscar en Finder)
# Suele ser algo como:
SHAREPOINT_DIR=/Users/raimundo/Library/CloudStorage/OneDrive-Toesca/Documentos

# Ruta completa a la carpeta Comercial (con subcarpetas 2025/, 2026/, etc.)
RENTA_COMERCIAL_DIR=/Users/raimundo/Library/CloudStorage/OneDrive-Toesca/Documentos/Rentas/Control de Gestión Rentas Inmobiliarias/Control de Gestión Históricos/Comercial
```

> **Cómo encontrar la ruta exacta en Mac:**
> Abre Finder → busca la carpeta OneDrive → arrastra la carpeta al Terminal para obtener la ruta completa.

### 4. Ejecutar el agente

```bash
source venv/bin/activate   # si no está activado
python agent.py
```

---

## Instalación en Windows

### 1. Clonar el repositorio

```bash
git clone https://github.com/raimundoopazotoesca/Agente-Toesca.git
cd Agente-Toesca
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar el `.env`

```bash
copy .env.example .env
```

Editar `.env`:

```env
GEMINI_API_KEY=tu_clave_de_google_ai_studio

# Ruta de la carpeta Comercial (SharePoint o R:)
RENTA_COMERCIAL_DIR=C:\Users\raimundo.opazo\OneDrive - Toesca\Documentos\Rentas\Control de Gestión Rentas Inmobiliarias\Control de Gestión Históricos\Comercial

# Opcional: servidor local R:
# LOCAL_FILES_DIR=R:\Planillas
```

### 4. Ejecutar

```bash
python agent.py
```

---

## Mantener sincronizado entre computadores

```bash
# Subir cambios
git add -A && git commit -m "descripción" && git push

# Bajar cambios en el otro computador
git pull
```

> El `.env` **no se sube a GitHub** (está en `.gitignore`). Cada computador tiene su propio `.env` con las rutas locales correctas.
