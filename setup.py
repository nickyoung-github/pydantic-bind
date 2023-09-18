from setuptools import find_packages, setup

# ToDo: Add versioneer

setup(name="pydantic_bind",
      version="1.1.3",
      description="C++/pybind generation from Pydantic classes",
      author="Nick Young",
      license=r"https://www.apache.org/licenses/LICENSE-2.0",
      packages=find_packages(),
      include_package_data=True,
      install_requires=[
          "pydantic>=2.0.2",
          "pybind11"
      ],
      classifiers=[
          "Programming Language :: Python :: 3",
          "Programming Language :: Python :: 3.11",
          "Operating System :: OS Independent",
          "License :: OSI Approved :: Apache Software License"
      ])
