"""Run WSGI server locally with waitress"""
import sys
from pathlib import Path

# Add src to path before importing anything
src_path = Path(__file__).resolve().parent / 'src'
sys.path.insert(0, str(src_path))

from waitress import serve
from config.wsgi import application

if __name__ == '__main__':
    print("Starting Waitress WSGI server on http://127.0.0.1:8000")
    print("Access at: http://localhost:8000/api/")
    serve(application, host='127.0.0.1', port=8000, threads=4)
