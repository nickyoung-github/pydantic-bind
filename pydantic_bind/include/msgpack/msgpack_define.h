//
// Created by Nick on 8/21/23.
//

#ifndef PYDANTIC_BIND_MSGPACK_DEFINE_H
#define PYDANTIC_BIND_MSGPACK_DEFINE_H

#define MSGPACK_DEFINE(...)
    template<class T>
    void msgpack(T &pack)
    {
        pack(__VA_ARGS__);
    }

#endif //PYDANTIC_BIND_MSGPACK_DEFINE_H
