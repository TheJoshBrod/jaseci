from __future__ import annotations
from jaclang.runtimelib.builtin import *
from jaclang import JacMachineInterface as _jl
for i in range(10):
    if i > 3:
        break
    print(i)
for j in range(5):
    if j == 2:
        continue
    print(j)
count = 0
while True:
    count += 1
    if count > 3:
        break
    print(count)
n = 0
while n < 5:
    n += 1
    if n % 2 == 0:
        continue
    print(n)

class SkipWalker(_jl.Walker):

    @_jl.on_entry
    def process(self, here) -> None:
        return
for x in range(3):
    for y in range(3):
        if x == y == 1:
            break
        print(f'{x},{y}')
for a in range(3):
    for b in range(3):
        if a == b:
            continue
        print(f'{a},{b}')
