import json

from amiyabot.network.httpRequests import http_requests


class CQHttpAPI:
    def __init__(self, address: str):
        self.address = address

    @classmethod
    def __json(cls, interface, res):
        try:
            return json.loads(res)
        except json.decoder.JSONDecodeError:
            return res

    def __url(self, interface):
        return f'http://{self.address}/{interface}'

    async def get(self, interface):
        res = await http_requests.get(self.__url(interface))
        if res:
            return self.__json(interface, res)

    async def post(self, interface, data):
        res = await http_requests.post(self.__url(interface), data)
        if res:
            return self.__json(interface, res)
