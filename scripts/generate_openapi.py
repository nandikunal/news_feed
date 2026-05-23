from app.main import app
import json

def main():
    schema = app.openapi()
    with open('docs/openapi.json','w') as f:
        json.dump(schema, f, indent=2)
    print('Wrote docs/openapi.json')

if __name__ == '__main__':
    main()
