import os
import time
import re
import io
import tempfile
import requests
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload
from pydub import AudioSegment

# Configurações da API do Google
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/documents']
SERVICE_ACCOUNT_FILE = 'credentials.json'

try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    print("Credenciais carregadas com sucesso.")
except Exception as e:
    print(f"Erro ao carregar credenciais: {e}")
    exit(1)

try:
    drive_service = build('drive', 'v3', credentials=credentials)
    docs_service = build('docs', 'v1', credentials=credentials)
    print("Serviços do Google API inicializados com sucesso.")
except Exception as e:
    print(f"Erro ao inicializar serviços do Google API: {e}")
    exit(1)

ASSEMBLYAI_API_KEY = '6a2d5263fa48453dafd57bfab28a3c5c'

def list_recent_files(folder_id):
    try:
        results = drive_service.files().list(
            q=f"'{folder_id}' in parents and mimeType contains 'audio/'",
            pageSize=10, fields="nextPageToken, files(id, name, createdTime)").execute()
        items = results.get('files', [])
        print(f"Arquivos recentes listados: {items}")
        return items
    except Exception as e:
        print(f"Erro ao listar arquivos: {e}")
        return []

def monitor_folder(folder_id):
    processed_files = set()
    while True:
        print("Verificando novos arquivos na pasta...")
        files = list_recent_files(folder_id)
        for file in files:
            if file['id'] not in processed_files:
                print(f"Processando arquivo: {file['name']}")
                process_file(file['id'], file['name'], folder_id)
                processed_files.add(file['id'])
        time.sleep(60)

def download_file(file_id, file_name):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, file_name)
        with open(file_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                print(f"Download em progresso: {int(status.progress() * 100)}%")
        print(f"Arquivo baixado em: {file_path}")
        return file_path
    except Exception as e:
        print(f"Erro ao baixar arquivo: {e}")
        return None

def preprocess_audio(file_path):
    try:
        audio = AudioSegment.from_file(file_path)
        normalized_audio = audio.normalize()
        filtered_audio = normalized_audio.low_pass_filter(3000)
        preprocessed_path = file_path.replace(".mp3", "_processed.wav")
        filtered_audio.export(preprocessed_path, format="wav")
        print(f"Áudio pré-processado salvo em: {preprocessed_path}")
        return preprocessed_path
    except Exception as e:
        print(f"Erro ao pré-processar áudio: {e}")
        return None

def upload_to_assemblyai(file_path):
    try:
        headers = {'authorization': ASSEMBLYAI_API_KEY}
        response = requests.post('https://api.assemblyai.com/v2/upload',
                                 headers=headers,
                                 data=open(file_path, 'rb'))
        upload_url = response.json().get('upload_url')
        print(f"Arquivo carregado para AssemblyAI: {upload_url}")
        return upload_url
    except Exception as e:
        print(f"Erro ao carregar arquivo para AssemblyAI: {e}")
        return None

def transcribe_audio(upload_url):
    try:
        endpoint = "https://api.assemblyai.com/v2/transcript"
        json = {
            "audio_url": upload_url,
            "punctuate": True,
            "format_text": True,
            "word_boost": ["Saga", "projetos", "clientes"],
            "language_code": "pt"  # Adiciona a configuração de idioma para português
        }
        headers = {"authorization": ASSEMBLYAI_API_KEY, "content-type": "application/json"}
        response = requests.post(endpoint, json=json, headers=headers)
        transcript_id = response.json().get('id')
        print(f"Transcrição iniciada com ID: {transcript_id}")
        return transcript_id
    except Exception as e:
        print(f"Erro ao iniciar transcrição: {e}")
        return None

def get_transcription_result(transcript_id):
    try:
        endpoint = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
        headers = {"authorization": ASSEMBLYAI_API_KEY}
        response = requests.get(endpoint, headers=headers)
        result = response.json()
        print(f"Resultado da transcrição: {result}")
        return result
    except Exception as e:
        print(f"Erro ao obter resultado da transcrição: {e}")
        return None

def create_google_doc(title, content, folder_id):
    try:
        document = docs_service.documents().create(body={"title": title}).execute()
        doc_id = document['documentId']
        
        requests = [
            {
                'insertText': {
                    'location': {'index': 1},
                    'text': content
                }
            }
        ]
        docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        print(f"Documento Google criado com ID: {doc_id}")

        drive_service.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents='root',
            fields='id, parents'
        ).execute()
        print(f"Documento movido para a pasta: {folder_id}")
    except Exception as e:
        print(f"Erro ao criar documento Google: {e}")

def analyze_transcription(text):
    saga_info = {
        'o que faz': None,
        'tipos de projetos': None,
        'tipos de clientes': None,
        'continentes': None
    }
    
    o_que_faz_match = re.search(r'nós somos a saga, somos uma consultoria de (.+?)(?:\.|,|;)', text, re.IGNORECASE)
    tipos_de_projetos_match = re.search(r'especializada em (projetos de [^,]+(?:, projetos de [^,]+)*)(?:\.|,|;)',
text, re.IGNORECASE)
    tipos_de_clientes_match = re.search(r'startups, (.+?)(?:\.|,|;)', text, re.IGNORECASE)
    continentes_match = re.search(r'todos os continentes', text, re.IGNORECASE)

    if o_que_faz_match:
        saga_info['o que faz'] = o_que_faz_match.group(1).strip()
    if tipos_de_projetos_match:
        saga_info['tipos de projetos'] = tipos_de_projetos_match.group(1).strip()
    if tipos_de_clientes_match:
        saga_info['tipos de clientes'] = tipos_de_clientes_match.group(1).strip()
    if continentes_match:
        saga_info['continentes'] = "todos os continentes"
    
    return saga_info

def save_transcription(text, folder_id):
    analysis = analyze_transcription(text)
    analysis_content = f"""
    Transcrição Completa:
    {text}
    
    Análise da Transcrição:
    
    O que a Saga faz: {analysis.get('o que faz', 'Informação não encontrada')}
    Tipos de projetos: {analysis.get('tipos de projetos', 'Informação não encontrada')}
    Tipos de clientes: {analysis.get('tipos de clientes', 'Informação não encontrada')}
    Em quantos continentes está: {analysis.get('continentes', 'Informação não encontrada')}
    """
    create_google_doc('Análise de Transcrição', analysis_content, folder_id)

def process_file(file_id, file_name, folder_id):
    file_path = download_file(file_id, file_name)
    preprocessed_audio_path = preprocess_audio(file_path)
    if preprocessed_audio_path:
        upload_url = upload_to_assemblyai(preprocessed_audio_path)
        transcript_id = transcribe_audio(upload_url)
        
        while True:
            result = get_transcription_result(transcript_id)
            if result['status'] == 'completed':
                save_transcription(result['text'], folder_id)
                break
            elif result['status'] == 'failed':
                print("Transcrição falhou")
                break
            time.sleep(30)

if __name__ == '__main__':
    folder_id = '14wjAh6RJmw9a3K3uQKctNp9H7m62uIm3'
    monitor_folder(folder_id)
