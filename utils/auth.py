

Live tail
GMT+3

Menu

           ^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/gunicorn/app/wsgiapp.py", line 48, in load_wsgiapp
    return util.import_app(self.app_uri)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/gunicorn/util.py", line 371, in import_app
    mod = importlib.import_module(module)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/importlib/__init__.py", line 126, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1204, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1176, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1147, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 690, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 940, in exec_module
  File "<frozen importlib._bootstrap>", line 241, in _call_with_frames_removed
  File "/app/main.py", line 8, in <module>
    from routes.trade import router as trade_router
  File "/app/routes/trade.py", line 22, in <module>
    @router.post("/execute", tags=["Trade"])
     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/fastapi/routing.py", line 944, in decorator
    self.add_api_route(
  File "/usr/local/lib/python3.11/site-packages/fastapi/routing.py", line 883, in add_api_route
    route = route_class(
            ^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/fastapi/routing.py", line 513, in __init__
    self.dependant = get_dependant(path=self.path_format, call=self.endpoint)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/fastapi/dependencies/utils.py", line 261, in get_dependant
    type_annotation, depends, param_field = analyze_param(
                                            ^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/fastapi/dependencies/utils.py", line 400, in analyze_param
    assert depends is None, f"Cannot specify `Depends` for type {type_annotation!r}"
           ^^^^^^^^^^^^^^^
AssertionError: Cannot specify `Depends` for type <class 'starlette.requests.Request'>
[2025-08-17 15:07:22 +0000] [10] [INFO] Worker exiting (pid: 10)
[2025-08-17 15:07:22 +0000] [7] [ERROR] Worker (pid:10) exited with code 3
[2025-08-17 15:07:22 +0000] [7] [ERROR] Shutting down: Master
[2025-08-17 15:07:22 +0000] [7] [ERROR] Reason: Worker failed to boot.
[2025-08-17 15:12:24 +0000] [7] [INFO] Starting gunicorn 21.2.0
[2025-08-17 15:12:24 +0000] [7] [INFO] Listening at: http://0.0.0.0:10000 (7)
[2025-08-17 15:12:24 +0000] [7] [INFO] Using worker: uvicorn.workers.UvicornWorker
[2025-08-17 15:12:24 +0000] [10] [INFO] Booting worker with pid: 10
[2025-08-17 15:12:26 +0000] [10] [ERROR] Exception in worker process
Traceback (most recent call last):
  File "/usr/local/lib/python3.11/site-packages/gunicorn/arbiter.py", line 609, in spawn_worker
    worker.init_process()
  File "/usr/local/lib/python3.11/site-packages/uvicorn/workers.py", line 68, in init_process
    super().init_process()
  File "/usr/local/lib/python3.11/site-packages/gunicorn/workers/base.py", line 134, in init_process
    self.load_wsgi()
  File "/usr/local/lib/python3.11/site-packages/gunicorn/workers/base.py", line 146, in load_wsgi
    self.wsgi = self.app.wsgi()
                ^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/gunicorn/app/base.py", line 67, in wsgi
    self.callable = self.load()
                    ^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/gunicorn/app/wsgiapp.py", line 58, in load
    return self.load_wsgiapp()
           ^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/gunicorn/app/wsgiapp.py", line 48, in load_wsgiapp
    return util.import_app(self.app_uri)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/gunicorn/util.py", line 371, in import_app
    mod = importlib.import_module(module)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/importlib/__init__.py", line 126, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1204, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1176, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1147, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 690, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 940, in exec_module
  File "<frozen importlib._bootstrap>", line 241, in _call_with_frames_removed
  File "/app/main.py", line 8, in <module>
    from routes.trade import router as trade_router
  File "/app/routes/trade.py", line 22, in <module>
    @router.post("/execute", tags=["Trade"])
     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/fastapi/routing.py", line 944, in decorator
    self.add_api_route(
  File "/usr/local/lib/python3.11/site-packages/fastapi/routing.py", line 883, in add_api_route
    route = route_class(
            ^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/fastapi/routing.py", line 513, in __init__
    self.dependant = get_dependant(path=self.path_format, call=self.endpoint)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/fastapi/dependencies/utils.py", line 261, in get_dependant
    type_annotation, depends, param_field = analyze_param(
                                            ^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/fastapi/dependencies/utils.py", line 400, in analyze_param
    assert depends is None, f"Cannot specify `Depends` for type {type_annotation!r}"
           ^^^^^^^^^^^^^^^
AssertionError: Cannot specify `Depends` for type <class 'starlette.requests.Request'>
[2025-08-17 15:12:26 +0000] [10] [INFO] Worker exiting (pid: 10)
[2025-08-17 15:12:26 +0000] [7] [ERROR] Worker (pid:10) exited with code 3
[2025-08-17 15:12:26 +0000] [7] [ERROR] Shutting down: Master
[2025-08-17 15:12:26 +0000] [7] [ERROR] Reason: Wor






