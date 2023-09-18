from distutils.core import setup

setup(name='pydantic_bind',
      version='1.0.1',
      description='C++/pybind generation from Pydantic classes',
      author='Nick Young',
      packages=['pydantic_bind'],
      requirements=[
          "pydantic>=2.0.2",
          "pybind11"
      ])

