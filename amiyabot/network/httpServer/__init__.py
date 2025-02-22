import os

from typing import Any
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter

from amiyabot.util import snake_case_to_pascal_case

from .serverBase import *

cur_file_path = os.path.abspath(__file__)
cur_file_folder = os.path.dirname(cur_file_path)


class HttpServer(metaclass=ServerMeta):
    def __init__(self,
                 host: str,
                 port: int,
                 title: str = 'AmiyaBot',
                 description: str = '<a href="https://www.amiyabot.com" target="__blank">https://www.amiyabot.com</a>',
                 auth_key: str = None,
                 fastapi_options: dict = None,
                 uvicorn_options: dict = None):
        self.app = FastAPI(title=title, description=description, **(fastapi_options or {}))
        self.server = self.__load_server(options={
            'host': host,
            'port': port,
            **(uvicorn_options or {})
        })
        self.router = InferringRouter()
        self.controller = cbv(self.router)

        self.__routes = []
        self.__allow_path = []

        @self.app.middleware('http')
        async def interceptor(request: Request, call_next: Callable):
            if not request.scope['path'] in self.__allow_path + ['/docs', '/favicon.ico', '/openapi.json']:
                if auth_key and request.headers.get('authKey') != auth_key:
                    return Response('Invalid authKey', status_code=401)
            return await call_next(request)

        @self.app.on_event('shutdown')
        def on_shutdown():
            HttpServer.shutdown_all(self.server)

    def set_allow_path(self, paths: list):
        self.__allow_path += paths

    def __load_server(self, options):
        return uvicorn.Server(config=uvicorn.Config(self.app,
                                                    loop='asyncio',
                                                    log_config=os.path.join(cur_file_folder,
                                                                            '../../_assets/serverLogger.yaml'),
                                                    **options))

    def route(self, router_path: str = None, method: str = 'post', allow_unauthorized: bool = False, **kwargs):
        def decorator(fn):
            nonlocal router_path

            path = fn.__qualname__.split('.')
            c_name = snake_case_to_pascal_case(path[0][0].lower() + path[0][1:])

            if not router_path:
                router_path = f'/{c_name}'
                if len(path) > 1:
                    router_path += f'/{snake_case_to_pascal_case(path[1])}'

            arguments = {
                'path': router_path,
                'tags': [c_name.title()] if len(path) > 1 else ['Alone'],
                **kwargs
            }

            router_builder = getattr(self.router, method)
            router = router_builder(**arguments)

            self.__routes.append(router_path)
            if allow_unauthorized:
                self.__allow_path.append(router_path)

            return router(fn)

        return decorator

    @staticmethod
    def response(data: Any = None, code: int = 200, message: str = ''):
        return {
            'data': data,
            'code': code,
            'message': message
        }

    async def serve(self):
        async with ServerLog.logger.catch('Http server Error:'):
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=['*'],
                allow_methods=['*'],
                allow_headers=['*'],
                allow_credentials=True
            )
            self.app.include_router(self.router)

            await self.server.serve()
