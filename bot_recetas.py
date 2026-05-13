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
            'anthropic-beta': 'pdfs-2024-09-27'
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            resp = json.loads(r.read().decode())
            texto = resp['content'][0]['text'].strip()
            
            # Limpiar el texto para encontrar solo el JSON usando regex por si mete comillas
            match = re.search(r'\{.*\}', texto, re.DOTALL)
            if match:
                texto = match.group(0)
                
            datos = json.loads(texto)
            datos['_fuente'] = f"Telegram: {nombre_archivo} (de {remitente})"
            datos['_importado'] = datetime.now().strftime("%Y-%m-%d %H:%M")
            datos['_estado'] = 'pendiente_revision'
            return datos
    except urllib.error.HTTPError as e:
        print(f"❌ Error Claude API: {e}")
        try:
            print("Detalle del error:", e.read().decode())
        except:
            pass
        return None
    except Exception as e:
        print(f"❌ Error Claude API: {e}")
        return None

def leer_offset():
    if os.path.exists('telegram_offset.txt'):
        try:
            with open('telegram_offset.txt', 'r') as f:
                return int(f.read().strip())
        except:
            pass
    return 0

def guardar_offset(offset):
    with open('telegram_offset.txt', 'w') as f:
        f.write(str(offset))

def cargar_pendientes():
    if os.path.exists('recetas_pendientes.json'):
        try:
            with open('recetas_pendientes.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def guardar_pendientes(lista):
    with open('recetas_pendientes.json', 'w', encoding='utf-8') as f:
        json.dump(lista, f, indent=2, ensure_ascii=False)

def main():
    print("🤖 Iniciando bot de recetas...")
    
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN no configurado")
        return
    if not CLAUDE_API_KEY:
        print("❌ CLAUDE_API_KEY no configurado")
        return
        
    offset = leer_offset()
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset + 1}&allowed_updates=[\"message\"]"
    
    try:
        with urllib.request.urlopen(url, context=ctx) as r:
            updates = json.loads(r.read().decode())
    except Exception as e:
        print(f"❌ Error contactando a Telegram: {e}")
        return
        
    if not updates.get('ok'):
        print(f"❌ Error en la respuesta de Telegram: {updates}")
        return
        
    mensajes = updates.get('result', [])
    print(f"📥 Se encontraron {len(mensajes)} mensajes nuevos.")
    
    if not mensajes:
        return
        
    pendientes = cargar_pendientes()
    max_offset = offset
    nuevas = 0
    
    for msg in mensajes:
        update_id = msg['update_id']
        max_offset = max(max_offset, update_id)
        
        m = msg.get('message', {})
        doc = m.get('document')
        remitente = m.get('from', {}).get('first_name', 'Usuario')
        
        if doc:
            nombre = doc.get('file_name', '')
            mime = doc.get('mime_type', '')
            
            # Comprobar si es PDF o imagen
            if mime == 'application/pdf' or nombre.lower().endswith('.pdf'):
                print(f"📄 Procesando PDF: {nombre} de {remitente}")
                pdf_bytes = descargar_pdf(doc['file_id'])
                if pdf_bytes:
                    # Extraer datos con Claude
                    datos = extraer_receta_claude(pdf_bytes, nombre, remitente)
                    if not datos:
                        print(f"   ❌ No se pudieron extraer datos de {nombre}")
                        datos = {
                            "finca": "", "plantacion": "", "fechaVisita": "", "fechaAplicacion": "",
                            "volumen": 0, "observaciones": "", "productos": [],
                            "_fuente": f"Telegram: {nombre} (de {remitente})",
                            "_importado": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "_estado": "error_extraccion",
                            "_error": "No se pudieron extraer datos automaticamente"
                        }
                    else:
                        print(f"   ✅ Extraido correctamente: {datos.get('finca', 'Desconocida')}")
                        
                    pendientes.insert(0, datos) # Añadir al principio
                    nuevas += 1
                    
    if nuevas > 0:
        if len(pendientes) > 50:
            pendientes = pendientes[:50]
        guardar_pendientes(pendientes)
        print(f"💾 Guardadas {nuevas} recetas nuevas en el archivo.")
        
    guardar_offset(max_offset)
    print("✅ Proceso terminado.")

if __name__ == "__main__":
    main()
