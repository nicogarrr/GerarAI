' GerarAI Backend — arranca el FastAPI (uvicorn) oculto, sin ventana.
' Registrado como Scheduled Task (ONLOGON) para que el scheduler de workers
' corra 24/7 mientras el PC este encendido (patron identico al Gateway).
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\nicoi\CavaAI\data-engine"
sh.Run """C:\Users\nicoi\CavaAI\data-engine\.venv\Scripts\python.exe"" -m uvicorn main:app --host 0.0.0.0 --port 8000", 0, False