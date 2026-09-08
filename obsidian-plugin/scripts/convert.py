import sys
import os

# The build process bundles the shared engine beside this wrapper.
sys.path.insert(0, os.path.dirname(__file__))

from engine.conversionEngine import ConversionEngine

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert.py <file_path> [api_key]")
        sys.exit(1)

    file_path = sys.argv[1]
    api_key = sys.argv[2] if len(sys.argv) > 2 else None
    engine = ConversionEngine(api_key=api_key)
    print(engine.convert(file_path))
