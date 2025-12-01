from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/calendar']

def get_service(service_name, version, creds_path): 
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES) 
    return build(service_name, version, credentials=creds)