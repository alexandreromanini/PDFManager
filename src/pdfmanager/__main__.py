import sys

from pdfmanager.app import main

if __name__ == "__main__":  # pas dans les processus de calcul (OCR…), qui importent ce module
    sys.exit(main())
