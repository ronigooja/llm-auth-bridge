"""Persistent worker entry point; browser adapters are intentionally isolated here."""
from .db import connect
def main():
    connect().close()
if __name__ == "__main__": main()

