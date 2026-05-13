import urllib.request
import urllib.error
import json
import base64
import os
import ssl
import re
from datetime import datetime

# Configuracion (estas variables se leen del entorno de GitHub)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_GROUP_ID = os.environ.get('TELEGRAM_GROUP_ID', '-852551974')
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')

# Deshabilitar validacion SSL estricta
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def descargar_pdf(file_id):
    """Descarga el PDF de Telegram en memoria"""
    try:
        url_info = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
        with urllib.request.urlopen(url_info, context=ctx) as r:
            info = json.loads(r.read().decode())
            file_path = info['result']['file_path']
        
        url_file = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        with urllib.request.urlopen(url_file, context=ctx) as r:
            return r.read()
    except Exception as e:
        print(f"❌ Error descargando archivo: {e}")
        return None

def extraer_receta_claude(pdf_bytes, nombre_archivo, remitente):
    """Envia el PDF a Claude para que extraiga los datos"""
    
    b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    
    prompt = """Analiza este documento que es una receta/recomendación de tratamiento fitosanitario agrícola.
Extrae TODOS los datos que encuentres y devuelve ÚNICAMENTE un JSON válido con esta estructura exacta:

{
  "finca": "nombre de la finca o parcela (suele venir bajo el epígrafe 'Finca')",
  "plantacion": "variedad o plantación (suele venir bajo 'Plantación' o 'Cultivo')",
  "fechaVisita": "YYYY-MM-DD (bajo 'Fecha Visita', asegúrate de convertir el formato a Año-Mes-Día)",
  "fechaAplicacion": "YYYY-MM-DD (bajo 'Fecha Aplicacion', en formato Año-Mes-Día)",
  "volumen": 0,
  "observaciones": "texto libre bajo 'Observaciones' (pon cadena vacía si no hay nada)",
  "productos": [
    {
      "nombre": "nombre comercial del producto",
      "principio": "materia activa si aparece",
      "dosis": 0
    }
  ]
}

Notas importantes:
- fechaVisita y fechaAplicacion deben ser obligatoriamente formato YYYY-MM-DD (ej: 2026-05-14). Convierte desde DD-MM-YYYY.
- dosis: busca bajo "Dosis ((gr-cc/100 l))" o la columna de cantidades. Extrae SOLO el número.
- volumen: busca bajo "Volumen de Caldo". Si pone 0, pon un número 0.
- productos: la lista suele tener el formato "NOMBRE DEL PRODUCTO" seguido de "CANTIDAD" y luego "[TIPO] MATERIA ACTIVA". Separa bien cada producto en un bloque de la lista.
- Si algún campo no aparece, pon cadena vacía "" o el número 0 según corresponda.
- Devuelve SOLO Y EXCLUSIVAMENTE texto JSON válido sin explicaciones adicionales."""

    payload = {
        "model": "claude-3-5-sonnet-latest",
        "max_tokens": 1500,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64_pdf
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    }

    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=json.dumps(payload).encode(),
        headers={
            'Content-Type': 'application/json',
            'x-api-key': CLAUDE_API_KEY,
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'pdfs-2024
