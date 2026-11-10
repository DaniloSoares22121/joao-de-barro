"""Sobe o servidor do João de Barro: python run.py  →  http://127.0.0.1:8870"""
import uvicorn

from lovable import config

if __name__ == "__main__":
    print(f"João de Barro em http://{config.HOST}:{config.PORT}")
    uvicorn.run("lovable.main:app", host=config.HOST, port=config.PORT, log_level="info")
