# import collections


class SuperLuxCoreLog:
    # add() is invoked from LuxCore engine threads while add/remove_listener
    # run on Blender's main thread — take copies instead of mutating in
    # place so iteration can never race.
    _listeners = []

    @staticmethod
    def add(msg):
        print(msg)

        for listener in list(SuperLuxCoreLog._listeners):
            listener(msg)

    @staticmethod
    def silent(msg):
        pass

    @classmethod
    def add_listener(cls, listener):
        cls._listeners = cls._listeners + [listener]

    @classmethod
    def remove_listener(cls, listener):
        cls._listeners = [l for l in cls._listeners if l is not listener]
