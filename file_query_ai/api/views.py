# api/views.py
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import requests
import json
import time

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
    
    # Enhanced prompt with data type handling
    full_prompt = f"""
    CSV columns: {columns[:10]}
    Sample data: {sample_data}
    Task: {user_prompt}
    
    IMPORTANT: CSV data is stored as strings. For numeric comparisons, convert to numbers.
    
    Generate JavaScript code using bracket notation: row['Column Name']
    
    Examples:
    - df.head(5)
    - df.data.filter(row => row['Gender'] === 'male' && parseInt(row['Age']) === 19)
    - df.data.filter(row => row['Fuel Type'] === 'Gasoline')
    - df.data.filter(row => parseFloat(row['Price']) > 20000)
    - df.count()
    
    For numeric comparisons, use:
    - parseInt(row['Age']) for integers
    - parseFloat(row['Price']) for decimals
    - row['Text Column'] === 'value' for text
    
    Return only the JavaScript expression.
    """

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system", 
                "content": """Generate browser-compatible JavaScript for CSV data. 
                
                CRITICAL: CSV values are strings. For numeric comparisons:
                - Use parseInt(row['Age']) === 19 for integer comparison
                - Use parseFloat(row['Price']) > 20.5 for decimal comparison
                - Use row['Name'] === 'text' for string comparison
                
                Always use bracket notation for columns."""
            },
            {"role": "user", "content": full_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 150,
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
                timeout=20  # 20 second timeout
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            
            # Clean up the response
            code = content.strip()
            
            # Remove markdown formatting if present
            if '```javascript' in code:
                start = code.find('```javascript') + 13
                end = code.find('```', start)
                if end != -1:
                    code = code[start:end].strip()
            elif '```' in code:
                start = code.find('```') + 3
                end = code.find('```', start)
                if end != -1:
                    code = code[start:end].strip()
            
            # Remove any Node.js specific code
            lines = code.split('\n')
            filtered_lines = []
            for line in lines:
                if not (('require(' in line) or ('const fs' in line) or ('csv-writer' in line)):
                    filtered_lines.append(line)
            
            code = '\n'.join(filtered_lines).strip()
            
            # Post-process: Fix any remaining dot notation issues
            code = fix_column_references(code, columns)
            
            return code
            
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                print(f"Timeout on attempt {attempt + 1}, retrying in {delay}s...")
                time.sleep(delay)
                continue
            else:
                return "❌ API Timeout: All retry attempts failed. Please try a simpler query."
                
        except Exception as e:
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
