import pytermgui as ptg

# Create a new window
window = ptg.Window(title="Hello World")

# Add a label to the window
label = ptg.Label(text="Hello, world!")
window.add_child(label)

# Add a button to the window
button = ptg.Button(text="Click me!", command=lambda: print("Button clicked!"))
window.add_child(button)

# Show the window
window.show()
