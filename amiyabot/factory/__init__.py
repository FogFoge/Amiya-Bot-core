import os
import shutil
import zipimport
import importlib

from amiyabot import log
from amiyabot.util import temp_sys_path, extract_zip
from amiyabot.builtin.lib.timedTask import tasks_control, CUSTOM_CHECK

from .factoryTyping import *
from .implemented import MessageHandlerItemImpl
from .factoryCore import ProcessControl


class BotHandlerFactory(ProcessControl):
    def __init__(self,
                 appid: str = None,
                 token: str = None,
                 adapter: Type[BotAdapterProtocol] = None):
        super().__init__()

        # override FactoryCore.plugins
        self.plugins: Dict[str, Union[BotHandlerFactory, PluginInstance]] = dict()

        self.appid = appid
        self.instance: Optional[BotAdapterProtocol] = None
        if adapter:
            self.instance = adapter(appid, token)

    @property
    def prefix_keywords(self) -> PrefixKeywords:
        return list(set(self.get_with_plugins()))

    @property
    def event_handlers(self) -> EventHandlers:
        return self.get_with_plugins()

    @property
    def message_handlers(self) -> MessageHandlers:
        return self.get_with_plugins()

    @property
    def exception_handlers(self) -> ExceptionHandlers:
        return self.get_with_plugins()

    @property
    def message_handler_id_map(self) -> MessageHandlersIDMap:
        return self.get_with_plugins()

    @property
    def group_config(self) -> Dict[str, GroupConfig]:
        return self.get_with_plugins()

    def on_message(self,
                   group_id: Union[GroupConfig, str] = None,
                   keywords: KeywordsType = None,
                   verify: VerifyMethodType = None,
                   check_prefix: CheckPrefixType = None,
                   allow_direct: Optional[bool] = None,
                   direct_only: bool = False,
                   level: int = None):
        """
        注册消息处理器

        :param group_id:      组别 ID
        :param keywords:      触发关键字
        :param verify:        自定义校验方法
        :param check_prefix:  是否校验前缀或指定需要校验的前缀
        :param allow_direct:  是否支持用于私信
        :param direct_only:   是否仅支持私信
        :param level:         关键字校验成功后函数的候选默认等级
        :return:              注册函数的装饰器
        """

        def register(func: FunctionType):
            handler = MessageHandlerItemImpl(func,
                                             group_id=str(group_id),
                                             group_config=self.group_config.get(str(group_id)),
                                             level=level,
                                             direct_only=direct_only,
                                             allow_direct=allow_direct,
                                             check_prefix=check_prefix,
                                             prefix_keywords=self.__get_prefix_keywords)
            if verify:
                handler.custom_verify = verify
            else:
                handler.keywords = keywords

            self.get_container('message_handler_id_map')[id(func)] = self.factory_name
            self.get_container('message_handlers').append(handler)

            return func

        return register

    def on_event(self, events: Union[str, List[str]] = '__all_event__'):
        """
        事件响应注册器

        :param events: 事件名或事件名列表
        :return:
        """

        def register(func: EventHandlerType):
            nonlocal events

            if not isinstance(events, list):
                events = [events]

            event_handlers = self.get_container('event_handlers')

            for item in events:
                if item not in event_handlers:
                    event_handlers[item] = []

                event_handlers[item].append(func)

            return func

        return register

    def on_exception(self, exceptions: Union[Type[Exception], List[Type[Exception]]] = Exception):
        """
        注册异常处理器，参数为异常类型或异常类型列表，在执行通过本实例注册的所有方法产生异常时会被调用

        :param exceptions: 异常类型或异常类型列表
        :return:           注册函数的装饰器
        """

        def handler(func: ExceptionHandlerType):
            nonlocal exceptions

            if not isinstance(exceptions, list):
                exceptions = [exceptions]

            exception_handlers = self.get_container('exception_handlers')

            for item in exceptions:
                if item not in exception_handlers:
                    exception_handlers[item] = []

                exception_handlers[item].append(func)

            return func

        return handler

    def timed_task(self, each: int = None, custom: CUSTOM_CHECK = None, sub_tag: str = 'default_tag'):
        def register(task: Callable[[BotHandlerFactory], Coroutine[Any, Any, None]]):
            @tasks_control.timed_task(each, custom, self.factory_name, sub_tag)
            async def _():
                await task(self)

            return task

        return register

    def remove_timed_task(self, sub_tag: str):
        tasks_control.remove_tag(self.factory_name, sub_tag)

    def set_group_config(self, config: GroupConfig):
        self.get_container('group_config')[config.group_id] = config

    def set_prefix_keywords(self, keyword: Union[str, List[str]]):
        prefix_keywords = self.get_container('prefix_keywords')
        prefix_keywords += [keyword] if not isinstance(keyword, list) else keyword

    def __get_prefix_keywords(self):
        return list(set(self.prefix_keywords))


class PluginInstance(BotHandlerFactory):
    def __init__(self,
                 name: str,
                 version: str,
                 plugin_id: str,
                 plugin_type: str = None,
                 description: str = None,
                 document: str = None):
        super().__init__()

        self.name = name
        self.version = version
        self.plugin_id = plugin_id
        self.plugin_type = plugin_type
        self.description = description
        self.document = document

        self.path = []

        self.factory_name = plugin_id

    def install(self): ...

    def uninstall(self): ...


class BotInstance(BotHandlerFactory):
    @classmethod
    def load_plugin(cls,
                    plugin: Union[str, PluginInstance],
                    extract_plugin: bool = False,
                    extract_plugin_dest: str = None):
        with log.sync_catch('plugin install error:'):
            if isinstance(plugin, str):
                if os.path.isdir(plugin):
                    # 以 Python Package 的形式加载
                    with temp_sys_path(os.path.dirname(plugin)):
                        module = importlib.import_module(os.path.basename(plugin))
                elif plugin.endswith('.py'):
                    # 以 py 文件的形式加载
                    with temp_sys_path(os.path.abspath(os.path.dirname(plugin))):
                        module = importlib.import_module(os.path.basename(plugin).strip('.py'))
                else:
                    # 以包的形式加载，方式同 Python Package
                    if not extract_plugin:
                        with temp_sys_path(os.path.abspath(plugin)):
                            module = zipimport.zipimporter(plugin).load_module('__init__')
                    else:
                        dest = os.path.abspath(extract_plugin_dest or os.path.splitext(plugin)[0].replace('.', '_'))

                        extract_zip(plugin, dest)

                        with temp_sys_path(os.path.dirname(dest)):
                            module = importlib.import_module(os.path.basename(dest))

                instance: PluginInstance = getattr(module, 'bot')
                instance.path.append(plugin)
                if extract_plugin:
                    instance.path.append(dest)
            else:
                instance = plugin

            return instance

    def install_plugin(self,
                       plugin: Union[str, PluginInstance],
                       extract_plugin: bool = False,
                       extract_plugin_dest: str = None):

        instance = self.load_plugin(plugin, extract_plugin, extract_plugin_dest)
        if not instance:
            return None

        plugin_id = instance.plugin_id

        assert plugin_id not in self.plugins, f'plugin id {plugin_id} already exists.'

        # 安装插件
        instance.set_prefix_keywords(self.prefix_keywords)
        instance.install()

        self.plugins[plugin_id] = instance

        return instance

    def uninstall_plugin(self, plugin_id: str, remove: bool = False):
        assert plugin_id != '__factory__' and plugin_id in self.plugins

        tasks_control.remove_tag(plugin_id)

        self.plugins[plugin_id].uninstall()

        if remove and self.plugins[plugin_id].path:
            for item in self.plugins[plugin_id].path:
                if os.path.isdir(item):
                    shutil.rmtree(item)
                else:
                    os.remove(item)

        del self.plugins[plugin_id]

    def combine_factory(self, factory: BotHandlerFactory):
        self.plugins['__factory__'] = factory
