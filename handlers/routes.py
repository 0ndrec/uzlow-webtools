from flask import render_template, url_for, redirect, flash, jsonify, request
from pathlib import Path
import importlib.util

# Load data about files in tools directory. Return dict with built-in python functions.
def load_tools()-> list:
    tools_dir = Path(__file__).parent.parent / "tools"
    tools = []
    for tool in tools_dir.iterdir():
        if tool.is_file() and tool.suffix == ".py":
            tool_name = tool.stem
            func_dict = {}
            try:
                # Import the module correctly using importlib
                import importlib
                spec = importlib.util.spec_from_file_location(f"tools.{tool_name}", str(tool))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Get all user-defined callable attributes that don't start with underscore
                for attr_name in dir(module):
                    if not attr_name.startswith("_"):
                        attr = getattr(module, attr_name)
                        if callable(attr) and getattr(attr, "__module__", None) == module.__name__:
                            func_dict[attr_name] = {
                                "doc": attr.__doc__ or "No documentation available",
                                "name": attr_name,
                                "parameters": attr.__code__.co_varnames[:attr.__code__.co_argcount],
                                "module": module.__name__
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
            tool_data['schema'] = getattr(module, 'DATAFLOW_SCHEMA', None)
        except Exception as e:
            print(f"Error loading schema for {tool_name}: {e}")

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
