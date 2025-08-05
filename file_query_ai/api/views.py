# api/views.py
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import requests
import json
import time

# 🔥 Updated API key
API_KEY = "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"
MODEL = "mistralai/mistral-7b-instruct"

@api_view(["POST"])
def generate_code(request):
    try:
        data = request.data
        columns = data.get('columns', [])
        query = data.get('query', '')
        sample_data = data.get('sample_data', [])
        
        if not columns or not query:
            return Response({"error": "Columns and query are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Format the query for the LLM
        formatted_query = process_user_query(query)
        
        # Generate code using OpenRouter API
        generated_code = call_openrouter_api(columns, formatted_query, sample_data)
        
        if generated_code.startswith("❌"):
            return Response({"error": generated_code}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            "success": True,
            "code": generated_code,
            "query": formatted_query,
            "columns": columns
        })
        
    except Exception as e:
        return Response({
            "error": f"Unexpected error: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def process_user_query(user_input):
    """Process user input to create a proper query for the LLM"""
    if user_input.lower().startswith(("give me", "create", "generate", "write")):
        return user_input
    return f"Generate JavaScript code to {user_input} using a data array"

def call_openrouter_api(columns, user_prompt, sample_data):
    """Call OpenRouter API with retry logic"""
    
    max_retries = 3
    base_delay = 2
    
    # 🔥 IMPROVED PROMPT - More specific and focused
    full_prompt = f"""
    You have a CSV file with these EXACT columns: {columns}
    
    User query: "{user_prompt}"
    
    Generate ONLY the JavaScript expression that answers this query.
    
    
    Your response:
    """

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system", 
                "content": """You are a JavaScript code generator. Generate ONLY executable JavaScript expressions for CSV data operations.

                Rules:
                1. Return ONLY the JavaScript code, no explanations or comments
                2. Use bracket notation for columns: row['Column Name']
                3. For numeric comparisons use parseInt() or parseFloat()
                4. No sample data, no examples, just the code
                
                Response format: Just the code expression"""
            },
            {"role": "user", "content": full_prompt}
        ],
        "temperature": 0.1,  # Very low temperature for consistent output
        "max_tokens": 50,    # 🔥 Reduced tokens to prevent long explanations
        "timeout": 25
    }

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "CSV Query Tool"
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(
                url, 
                headers=headers, 
                json=payload,
                timeout=20
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            
            print(f"Raw API response: {content}")  # 🔥 Debug output
            
            # 🔥 AGGRESSIVE CLEANING - Extract only the code
            code = content.strip()
            
            # Remove any explanatory text before the code
            lines = code.split('\n')
            code_line = None
            
            for line in lines:
                line = line.strip()
                # Look for lines that start with df. or data. or contain filter/head/tail/count
                if (line.startswith('df.') or 
                    line.startswith('data.') or 
                    'filter(' in line or 
                    '.head(' in line or 
                    '.tail(' in line or 
                    '.count(' in line or 
                    '.columns' in line):
                    code_line = line
                    break
            
            if code_line:
                code = code_line
            
            # Remove markdown formatting
            if '```' in code:
                # Extract code from markdown blocks
                if '```javascript' in code:
                    start = code.find('```javascript') + 13
                    end = code.find('```', start)
                    if end != -1:
                        code = code[start:end].strip()
                else:
                    start = code.find('```') + 3
                    end = code.find('```', start)
                    if end != -1:
                        code = code[start:end].strip()
            
            # Remove any remaining explanatory text
            code = code.split('\n')[0]  # Take only the first line
            
            # Remove common prefixes
            prefixes_to_remove = [
                "Here's the code:",
                "The JavaScript expression is:",
                "Expression:",
                "Code:",
                "Answer:",
                "Result:"
            ]
            
            for prefix in prefixes_to_remove:
                if code.startswith(prefix):
                    code = code[len(prefix):].strip()
            
            # Clean up any remaining artifacts
            code = code.replace('`', '').strip()
            
            # Remove semicolons at the end
            code = code.rstrip(';')
            
            print(f"Cleaned code: {code}")  # 🔥 Debug output
            
            # Post-process: Fix any remaining issues
            code = fix_column_references(code, columns)
            
            return code
            
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"Timeout on attempt {attempt + 1}, retrying in {delay}s...")
                time.sleep(delay)
                continue
            else:
                return "❌ API Timeout: All retry attempts failed. Please try a simpler query."
                
        except Exception as e:
            print(f"API Error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return f"❌ API Error: {e}"

def fix_column_references(code, actual_columns):
    """Fix column references and add numeric conversions"""
    import re
    
    # Fix dot notation to bracket notation
    dot_patterns = re.findall(r'row\.([A-Za-z_][A-Za-z0-9_]*)', code)
    
    for pattern in dot_patterns:
        for actual_col in actual_columns:
            simplified_actual = actual_col.replace(' ', '_').replace('.', '_').replace('-', '_')
            
            if simplified_actual.lower() == pattern.lower():
                old_ref = f"row.{pattern}"
                new_ref = f"row['{actual_col}']"
                code = code.replace(old_ref, new_ref)
                print(f"Fixed column reference: {old_ref} -> {new_ref}")
                break
    
    # Fix numeric comparisons - look for patterns like row['Age'] === 19
    numeric_patterns = re.findall(r"row\['([^']+)'\]\s*([<>=!]+)\s*(\d+)", code)
    
    for column, operator, number in numeric_patterns:
        # Check if this looks like a numeric column
        if any(keyword in column.lower() for keyword in ['age', 'year', 'count', 'number', 'id', 'price', 'amount', 'quantity']):
            old_pattern = f"row['{column}'] {operator} {number}"
            new_pattern = f"parseInt(row['{column}']) {operator} {number}"
            code = code.replace(old_pattern, new_pattern)
            print(f"Fixed numeric comparison: {old_pattern} -> {new_pattern}")
    
    # Fix decimal comparisons
    decimal_patterns = re.findall(r"row\['([^']+)'\]\s*([<>=!]+)\s*(\d+\.\d+)", code)
    
    for column, operator, number in decimal_patterns:
        if any(keyword in column.lower() for keyword in ['price', 'amount', 'rate', 'percentage', 'score']):
            old_pattern = f"row['{column}'] {operator} {number}"
            new_pattern = f"parseFloat(row['{column}']) {operator} {number}"
            code = code.replace(old_pattern, new_pattern)
            print(f"Fixed decimal comparison: {old_pattern} -> {new_pattern}")
    
    return code
