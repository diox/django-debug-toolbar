import time
import sys
import traceback

import django.dispatch
from django.core.cache import get_cache
from django.core.cache.backends.base import BaseCache
from django.template.loader import render_to_string
from django.utils.translation import ugettext_lazy as _
from debug_toolbar.panels import DebugPanel
from debug_toolbar.panels.sql import tidy_stacktrace

cache_call = django.dispatch.Signal(providing_args=["time_taken", "name", "return_value", "args", "trace"])

def debug_cache_backend(dummy, params):
    backend = 'BACKEND_TO_MONITOR' in params and params['BACKEND_TO_MONITOR'] or 'default'
    cache = get_cache(backend)
    return CacheStatTracker(cache)

class CacheStatTracker(BaseCache):
    """A small class used to track cache calls."""
    def __init__(self, cache):
        self.cache = cache
        
    def _send_call_signal(method):
        def wrapped(self, *args, **kwargs):
            t = time.time()
            value = method(self, *args, **kwargs)
            t = time.time() - t
            
            # FIXME: factorize this, it's copy/pasted from sql.py
            stacktrace = tidy_stacktrace(traceback.extract_stack())
            template_info = None
            cur_frame = sys._getframe().f_back
            try:
                while cur_frame is not None:
                    if cur_frame.f_code.co_name == 'render':
                        node = cur_frame.f_locals['self']
                        if isinstance(node, Node):
                            template_info = get_template_info(node.source)
                            break
                    cur_frame = cur_frame.f_back
            except:
                pass
            del cur_frame
            
            cache_call.send(sender=self, time_taken=t, name=method.__name__,
                            return_value=value, args=args[0], 
                            trace=stacktrace, template_info=template_info)
            return value
        return wrapped
        
    def _get_func_info(self):
        stack = inspect.stack()[2]
        return (stack[1], stack[2], stack[3], stack[4])    
    
    @_send_call_signal
    def add(self, key, value, timeout=None, version=None):
        return self.cache.add(key, value, timeout, version)

    @_send_call_signal
    def get(self, key, default=None, version=None):
        return self.cache.get(key, default, version)

    @_send_call_signal
    def set(self, key, value, timeout=None, version=None):
        return self.cache.set(key, value, timeout, version)    

    @_send_call_signal
    def delete(self, key, version=None):
        return self.cache.get(key, version)

    @_send_call_signal
    def get_many(self, keys, version=None):
        return self.cache.get_many(key, version)

    @_send_call_signal
    def has_key(self, key, version=None):
        return self.cache.has_key(key, version)

    @_send_call_signal
    def incr(self, key, delta=1, version=None):
        return self.cache.incr(key, delta, version)

    @_send_call_signal
    def decr(self, key, delta=1, version=None):
        return self.cache.decr(key, delta, version)

    @_send_call_signal
    def set_many(self, data, timeout=None, version=None):
        return self.cache.set_many(data, timeout, version)

    @_send_call_signal
    def delete_many(self, keys, version=None):
        return self.cache.delete_many(keys, version)

    @_send_call_signal
    def clear(self):
        return self.cache.clear()

class CacheDebugPanel(DebugPanel):
    """
    Panel that displays the cache statistics.
    """
    name = 'Cache'
    has_content = True

    def __init__(self, *args, **kwargs):
        super(self.__class__, self).__init__(*args, **kwargs)
        self.total_time = 0
        self.hits = 0
        self.misses = 0
        self.calls = []
        self.stats = {
            'add' : 0,
            'get' : 0,
            'set' : 0,
            'delete' : 0,
            'get_many' : 0,
            'set_many' : 0,
            'delete_many' : 0,
            'has_key' : 0,
            'incr' : 0,
            'decr' : 0            
        }
        cache_call.connect(self._store_call_info)
        
    def _store_call_info(self, sender, name=None, time_taken=0, return_value=None, args=None, trace=None, **kwargs):
        if name == 'get':
            if return_value is None:
                self.misses += 1
            else:
                self.hits += 1
        elif name == 'get_many':
            for key, value in return_value.iteritems():
                if value is None:
                    self.misses += 1
                else:
                    self.hits += 1
        self.total_time += time_taken * 1000
        self.stats[name] += 1            
        self.calls.append({
            'time' : time_taken,
            'name' : name, 
            'args' : unicode(args), 
            'trace': trace,
            'template_info': kwargs.get('template_info', None)
        })

    def nav_title(self):
        return _('Cache: %.2fms') % self.total_time

    def title(self):
        return _('Cache Usage')

    def url(self):
        return ''

    def content(self):
        context = self.context.copy()
        context.update({
            'cache_total_calls': len(self.calls),
            'cache_calls' : self.calls,
            'cache_time': self.total_time,
            'cache_hits': self.hits,
            'cache_misses': self.misses,
            'cache_stats' : self.stats
        })
        return render_to_string('debug_toolbar/panels/cache.html', context)
