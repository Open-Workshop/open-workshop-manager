import os,sys,time,threading,subprocess,socket,urllib.request,tempfile
from concurrent import futures
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import grpc
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2,trace_service_pb2_grpc
spans=[]; received=[]
class Collector(trace_service_pb2_grpc.TraceServiceServicer):
 def Export(self, request, context):
  for resource in request.resource_spans:
   for scope in resource.scope_spans: spans.extend(scope.spans)
  return trace_service_pb2.ExportTraceServiceResponse()
class Upstream(BaseHTTPRequestHandler):
 def do_GET(self):
  received.append(self.headers.get('traceparent')); self.send_response(200)
  is_large = '/mods/42/' in self.path
  self.send_header('Content-Length',str(8*1024*1024 if is_large else 5));self.send_header('Content-Type','application/octet-stream');self.end_headers()
  try:
   if is_large:
    for _ in range(128): self.wfile.write(b'x' * 65536); self.wfile.flush(); time.sleep(.005)
   else:self.wfile.write(b'hello')
  except (BrokenPipeError, ConnectionResetError): pass
 def log_message(self,*a):pass
collector=grpc.server(futures.ThreadPoolExecutor(max_workers=2));trace_service_pb2_grpc.add_TraceServiceServicer_to_server(Collector(),collector);collector.add_insecure_port('127.0.0.1:24181');collector.start()
http=ThreadingHTTPServer(('127.0.0.1',24183),Upstream);threading.Thread(target=http.serve_forever,daemon=True).start()
d=tempfile.mkdtemp(prefix='ow-otel-nginx-test-');module='/home/miskler/ow-nginx-otel/nginx-otel/build/ngx_otel_module.so'; binary='/home/miskler/ow-nginx-otel/nginx-1.30.7/objs/nginx'
conf=f'''load_module {module};
env OW_NGINX_OTEL_UPSTREAM=1;
worker_processes 1; daemon off; pid {d}/nginx.pid; error_log {d}/error.log info;
events {{ worker_connections 128; }}
http {{ access_log off; otel_exporter {{ endpoint 127.0.0.1:24181; interval 1s; }} otel_service_name nginx-storage; otel_trace on; otel_trace_context propagate;
server {{ listen 127.0.0.1:24182; server_name storage.openworkshop.miskler.ru; location /download/ {{ proxy_buffering off; proxy_pass http://127.0.0.1:24183; }} location /plain {{ return 200 "x"; }} }} }}'''
open(d+'/nginx.conf','w').write(conf)
p=subprocess.Popen([binary,'-p',d,'-c',d+'/nginx.conf'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
try:
 for i in range(50):
  if p.poll() is not None: raise RuntimeError('nginx exited: '+p.stderr.read().decode())
  try:
   r=urllib.request.urlopen('http://127.0.0.1:24182/download/archive/mods/7515/main.zip?secret=hidden',timeout=2);assert r.read()==b'hello';break
  except OSError:time.sleep(.1)
 else:raise RuntimeError('nginx did not start')
 for i in range(50):
  if len(spans)>=3:break
  time.sleep(.1)
 print('received',len(spans),'spans',flush=True)
 by={s.name:s for s in spans};print('names',list(by),flush=True)
 assert len(spans)==3 and 'Send file to client' in by
 root=next(s for s in spans if s.kind==2); proxy=next(s for s in spans if s.kind==3); send=by['Send file to client']
 assert proxy.parent_span_id == root.span_id and send.parent_span_id == root.span_id
 assert received[0].split('-')[2] == proxy.span_id.hex(), (received[0],proxy.span_id.hex())
 assert root.trace_id == proxy.trace_id == send.trace_id
 def attrs(s):
  out={}
  for kv in s.attributes:
   field=kv.value.WhichOneof('value');out[kv.key]=getattr(kv.value,field)
  return out
 pa=attrs(proxy);sa=attrs(send);print('proxy',pa,flush=True);print('delivery',sa,flush=True)
 assert pa['http.url']=='http://127.0.0.1:24183/download/archive/mods/7515/main.zip'
 for k,v in {'ow.owner.type':'mod','ow.owner.id':'7515','ow.resource.id':'main','file.extension':'zip','file.size':5,'ow.transfer.bytes_sent':5,'ow.transfer.percent_sent':100.0,'ow.transfer.result':'complete','ow.transfer.scope':'nginx_to_client','ow.transfer.measurement':'socket_bytes_written'}.items():assert sa.get(k)==v,(k,sa.get(k),v)
 assert root.start_time_unix_nano<=proxy.start_time_unix_nano<=proxy.end_time_unix_nano<=root.end_time_unix_nano
 assert root.start_time_unix_nano<=send.start_time_unix_nano<=send.end_time_unix_nano<=root.end_time_unix_nano
 print('PASS proxy propagation, client transfer, size, percentage, object/resource identity and timing',flush=True)
 before=len(spans)
 sock=socket.create_connection(('127.0.0.1',24182));sock.sendall(b'GET /download/resource/mods/42/9.webp HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n');sock.recv(8192);sock.close()
 for i in range(60):
  if len(spans)>=before+3:break
  time.sleep(.1)
 later=spans[before:];delivery=next(s for s in later if s.name=='Send file to client');data=attrs(delivery);print('aborted delivery',data,flush=True)
 assert data['ow.owner.id']=='42' and data['ow.resource.id']=='9' and data['file.extension']=='webp'
 assert data['file.size']==8*1024*1024 and data['ow.transfer.result']=='interrupted' and data['ow.transfer.bytes_sent'] < data['file.size'] and 0<=data['ow.transfer.percent_sent']<100
 print('PASS interrupted transfer accounting',flush=True)
finally:
 p.terminate()
 try:p.wait(timeout=5)
 except subprocess.TimeoutExpired:p.kill()
 http.shutdown();collector.stop(0)
