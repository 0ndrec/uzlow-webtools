from flask import render_template, url_for, redirect, flash
from pathlib import Path

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
        tools = None
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
            
        return render_template("tool.html", title=f"Tool: {tool_name}", tool=tool_data)


    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("error.html", title="Page Not Found" + str(e), error=404)

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template("error.html", title="Method Not Allowed" + str(e), error=405)
    
    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", title="Bad Request" + str(e), error=400)
