import io,json,time,wave,threading
lock=threading.Lock()
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
buffer=io.BytesIO()
with wave.open(buffer,'wb') as wav:
 wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*16000)
audio=buffer.getvalue();counter=Path('/tmp/knowledge-e2e-asr-calls.json');counter.write_text('[]')
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_HEAD(self):self.send_response(200);self.send_header('Content-Type','audio/wav');self.send_header('Content-Length',str(len(audio)));self.end_headers()
 def do_GET(self):
  self.send_response(200);self.send_header('Content-Type','audio/wav');self.send_header('Content-Length',str(len(audio)));self.end_headers();self.wfile.write(audio)
 def do_POST(self):
  with lock:
   data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls=json.loads(counter.read_text());calls.append({'time':time.time(),'model':data.get('model')});counter.write_text(json.dumps(calls))
  payload=json.dumps({'text':'验收音频识别成功','segments':[]}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
ThreadingHTTPServer(('0.0.0.0',8770),Handler).serve_forever()
