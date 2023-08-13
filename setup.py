from setuptools import find_packages, setup

setup(name='pydantic_bind',
      version='1.0.2',
      description='C++/pybind generation from Pydantic classes',
      author='Nick Young',
      license=r"https://www.apache.org/licenses/LICENSE-2.0",
      packages=find_packages(),
      install_requires=[
          "pydantic>=2.0.2",
          "pybind11"
      ])
