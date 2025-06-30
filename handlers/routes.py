from flask import render_template, url_for, redirect, flash, jsonify, request
from pathlib import Path
import importlib.util
import importlib
import inspect

# Load data about files in tools directory. Return dict with built-in python functions.
def load_tools()-> list:
    tools_dir = Path(__file__).parent.parent / "tools"
    tools = []
    
    for tool in tools_dir.iterdir():
        if tool.is_file() and tool.suffix == ".py":
            tool_name = tool.stem
            func_dict = {}
            try:
                spec = importlib.util.spec_from_file_location(f"tools.{tool_name}", str(tool))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Inspect all module members
                for name, member in inspect.getmembers(module):
                    # Skip private members
                    if name.startswith('_'):
                        continue
                        
                    # Check if it's a class defined in this module
                    if inspect.isclass(member) and member.__module__ == module.__name__:
                        # Get class methods
                        for method_name, method in inspect.getmembers(member, predicate=inspect.isfunction):
                            if not method_name.startswith('_'):
                                # Get method signature
                                sig = inspect.signature(method)
                                parameters = list(sig.parameters.keys())
                                if 'self' in parameters:  # Remove 'self' from instance methods
                                    parameters.remove('self')
                                    
                                func_dict[f"{name}.{method_name}"] = {
                                    "doc": method.__doc__ or "No documentation available",
                                    "name": method_name,
                                    "class": name,
                                    "parameters": parameters,
                                    "module": module.__name__,
                                    "is_class_method": True
                                }
                    
                    # Check if it's a function defined in this module
                    elif inspect.isfunction(member) and member.__module__ == module.__name__:
                        sig = inspect.signature(member)
                        func_dict[name] = {
                            "doc": member.__doc__ or "No documentation available",
                            "name": name,
                            "parameters": list(sig.parameters.keys()),
                            "module": module.__name__,
                            "is_class_method": False
                        }
                        
            except Exception as e:
                print(f"Error importing {tool_name}: {e}")
            
            if func_dict:  # Only add tools that have functions
                tools.append({
                    "name": tool_name,
                    "functions": func_dict,
                    "path": str(tool.relative_to(tools_dir))
                })
    
    return tools


def configure_routes(app):

    @app.route("/")
    def index():
        tools = load_tools()
        return render_template("index.html", title="Uzlow Web Tools", tools=tools)
    
    @app.route("/about")
    def about():
        return render_template("about.html", title="About")
    
    @app.route("/t/<tool_name>")
    def tool(tool_name):
        tools = load_tools()
        tool_data = next((tool for tool in tools if tool["name"] == tool_name), None)
        if tool_data is None:
            flash("Tool not found", "error")
            return redirect(url_for("index"))

        # Get the schema from the module
        tools_dir = Path(__file__).parent.parent / "tools"
        tool_path = tools_dir / f"{tool_name}.py"
        try:
            spec = importlib.util.spec_from_file_location(f"tools.{tool_name}", str(tool_path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            schema = getattr(module, 'DATAFLOW_SCHEMA', None)
            if schema and 'input' in schema:
                # Restructure the schema for the template
                input_fields = {}
                if 'properties' in schema['input']:
                    for field_name, field_props in schema['input']['properties'].items():
                        input_fields[field_name] = {
                            'type': field_props.get('type', 'string'),
                            'required': field_name in schema['input'].get('required', []),
                            'enum': field_props.get('enum'),
                            'default': field_props.get('default')
                        }
                schema['input'] = input_fields
            tool_data['schema'] = schema
        except Exception as e:
            print(f"Error loading schema for {tool_name}: {e}")
            tool_data['schema'] = None

        return render_template("tool.html", title=f"Tool: {tool_name}", tool=tool_data)

    @app.route("/t/<tool_name>/run", methods=['POST'])
    def run_tool(tool_name):
        tools = load_tools()
        tool_data = next((tool for tool in tools if tool["name"] == tool_name), None)
        
        if tool_data is None:
            return jsonify({"error": "Tool not found"}), 404
            
        try:
            # Import the module
            tools_dir = Path(__file__).parent.parent / "tools"
            tool_path = tools_dir / f"{tool_name}.py"
            
            spec = importlib.util.spec_from_file_location(f"tools.{tool_name}", str(tool_path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Get the schema if it exists
            schema = getattr(module, 'DATAFLOW_SCHEMA', None)
            if not schema:
                return jsonify({"error": "Tool has no schema defined"}), 400
                
            # Get the entrypoint function
            entrypoint = getattr(module, schema['entrypoint'], None)
            if not entrypoint:
                return jsonify({"error": "Tool entrypoint not found"}), 400
              # Execute with or without input
            if schema.get('input') is None:
                # If no input is required in schema, just run the entrypoint
                result = entrypoint()
            else:
                # If input is required, get it from request
                input_data = request.get_json(silent=True)  # silent=True prevents parsing errors
                if input_data is None:
                    return jsonify({"error": "Input required but not provided"}), 400
                result = entrypoint(input_data)
            
            return jsonify({"success": True, "result": result})
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("error.html", title="Page Not Found" + str(e), error=404)

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template("error.html", title="Method Not Allowed" + str(e), error=405)
    
    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", title="Bad Request" + str(e), error=400)
