from openmed import analyze_text, ModelLoader
 
# Test basic import
loader = ModelLoader()
print(loader.list_available_models()[:5])