from utils.random import Random
from object import factory as of
from docs import get_object_offsprings, get_object_ancestors

import itertools
from abc import abstractmethod


class ObjectPool:
    def __init__(self, prefix):
        self.pool = {}
        self.count = 0
        self.prefix = prefix

    def objects(self):
        return self.pool.values()

    def get(self, name):
        return self.pool.get(name)

    def create_id(self):
        self.count += 1
        return "{}{}".format(self.prefix, self.count)

    def add(self, o):
        # add into pool
        name = o.name
        if name not in self.pool:
            self.pool[name] = []
        self.pool[name].append(o)

        # naming
        if o.id is None:
            o.id = self.create_id()

        return o


class Context:
    def __init__(self, prefix):
        self.object_pool = ObjectPool(prefix)

    # Object
    def create_object(self, name):
        o = of.create_object(name)
        self.add_object(o)
        return o

    def add_object(self, o):
        self.object_pool.add(o)

    @abstractmethod
    def get_objects(self, names):
        raise NotImplementedError

    def get_object(self, names):
        objs = self.get_objects(names)
        return Random.choice(objs)


class DOMContext(Context):
    def __init__(self, token_limit):
        super().__init__("x")
        self.superset = set()
        self.in_tree_set = set()
        self.token_limit = token_limit

        self.rdfuzz_superset = set()
        self.rdfuzz_subtree = []

    @property
    def in_tree_elements(self):
        return [o for o in itertools.chain.from_iterable(self.object_pool.objects()) if o.is_element]

    @property
    def rdfuzz_subbox(self):
        if len(self.rdfuzz_subtree) == 0:
            def get_descendants(element):
                if not element or not element.children: return []
                descendants = []
                children = element.children
                descendants.extend(descendants)
                for child in children:
                    descendants.extend(get_descendants(child))
                return descendants
            
            subbox_core_element = Random.choice(self.in_tree_elements)
            self.rdfuzz_subtree.extend(get_descendants(subbox_core_element))
            parent = subbox_core_element
            while parent:
                self.rdfuzz_subtree.append(parent)
                parent = parent.parent
            
            # update rdfuzz superset
            for o in self.rdfuzz_subtree:
                ancestors = get_object_ancestors(o.name)
                for ancestor in ancestors:
                    if ancestor not in self.rdfuzz_superset:
                        self.rdfuzz_superset.add(ancestor)

        return self.rdfuzz_subtree

    # Token
    def get_token(self, token):
        return "{}{}".format(token, Random.selector(self.token_limit[token]))

    def get_tokens(self, token):
        return ["{}{}".format(token, i) for i in range(self.token_limit[token])]

    def add_object(self, o):
        super().add_object(o)

        # update superset
        ancestors = get_object_ancestors(o.name)
        for ancestor in ancestors:
            if ancestor not in self.superset:
                self.superset.add(ancestor)

        # update in-tree element
        if o.is_element:
            self.in_tree_set.add(o.name)

    def get_objects(self, names):
        ret = self.get_rdfuzz_objects(names)
        if len(ret) > 0: return ret

        for name in names:
            objs = self.object_pool.get(name)
            if objs is not None:
                ret.extend(objs)
        return ret
    
    def get_rdfuzz_objects(self, names):
        ret = []
        for obj in self.rdfuzz_subbox:
            if obj.name in names:
                ret.append(obj)
        return ret



class JSContext(Context):
    def __init__(self, global_context):
        super().__init__("v")
        self.line = 0
        self.superset = {}
        self.locations = {}
        self.global_context = global_context

    @property
    def superset_at_line(self):
        # return self.global_context.superset | {name for name, line in self.superset.items() if line < self.line}
        return self.global_context.rdfuzz_superset | {name for name, line in self.superset.items() if line < self.line}

    def add_object(self, o): 
        super().add_object(o)

        # update superset
        ancestors = get_object_ancestors(o.name)
        for ancestor in ancestors:
            if ancestor not in self.superset:
                self.superset[ancestor] = self.line

        # update location
        self.locations[o.id] = self.line

    def get_objects(self, names):
        global_objects = self.global_context.get_objects(names)
        local_objects = []
        for name in names:
            objs = self.object_pool.get(name)
            if objs is not None:
                local_objects.extend(objs)
        return global_objects + [o for o in local_objects if self.locations[o.id] < self.line]

    def get_offsprings(self, name):
        names = get_object_offsprings(name)
        return self.get_objects(names)

    def get_offspring(self, name):
        objs = self.get_offsprings(name)
        return Random.choice(objs)

    # we only need the objects on the rdfuzz_subbox
    def rdfuzz_contains(self, name):
        return (name in self.global_context.rdfuzz_superset) or \
               (name in self.superset and self.superset[name] < self.line)

    def contains(self, name):
        return self.rdfuzz_contains(name)
        return (name in self.global_context.superset) or \
               (name in self.superset and self.superset[name] < self.line)

    def shift_object_location(self, begin):
        for oid in self.locations:
            if self.locations[oid] >= begin:
                self.locations[oid] += 1

        for name in self.superset:
            if self.superset[name] >= begin:
                self.superset[name] += 1
