from services.ai_service import extract_concepts

text = """
Machine Learning is a branch of Artificial Intelligence.
Neural Networks are inspired by the human brain.
"""

concepts = extract_concepts(text)

print(concepts)