with open('ui/simulation_widget.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the import
old_import = "from PyQt6.QtWidgets import QOpenGLWidget"
new_import = "from PyQt6.QtOpenGLWidgets import QOpenGLWidget"

content = content.replace(old_import, new_import)

with open('ui/simulation_widget.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed OpenGL import')
