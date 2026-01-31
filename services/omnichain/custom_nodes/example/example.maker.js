(function ExampleJsonProviderNode() {
  const doc = [
      "A variation of the GrabText node, built for demonstration purposes.",
      "The only difference is that this node has an empty JSON object as a string",
      "as its default value.",
      "Grabs text data from the 'data in' input, stores it in the node,",
      "and then fires the 'trigger out' output.",
      "Other nodes can use the 'data out' output to access the data",
      "stored in this node as many times as needed.",
      "This node will only grab new data and update itself if another",
      "node sends a signal via the 'trigger in' input.",
      "To clear the node's data, send a signal via the 'trigger clear' input.",
      "The 'trigger cleared' output will fire when the data is cleared.",
  ]
      .join(" ")
      .trim();

  return global.__ocMakeNode(
      {
          nodeName: "ExampleJsonObjectProviderNode",
          nodeIcon: "FileTextOutlined",
          dimensions: [580, 670],
          doc,
      },
      {
          inputs: [
              { name: "triggerIn", type: "trigger", label: "trigger in" },
              {
                  name: "triggerClear",
                  type: "trigger",
                  label: "trigger clear",
              },
              { name: "dataIn", type: "string", label: "data in" },
          ],
          outputs: [
              {
                  name: "triggerOut",
                  type: "trigger",
                  label: "trigger got data",
              },
              {
                  name: "triggerCleared",
                  type: "trigger",
                  label: "trigger cleared",
              },
              { name: "dataOut", type: "string", label: "data out" },
          ],
          controls: [
              {
                  name: "val",
                  control: {
                      type: "text",
                      defaultValue: "{}",
                      config: { large: true },
                  },
              },
          ],
      },
      {
          async controlFlow(nodeId, context, trigger) {
              try {
                  if (trigger === "triggerClear") {
                      await context.updateControl(nodeId, "val", "{}");
                      return "triggerCleared";
                  }

                  const inputs = await context.fetchInputs(nodeId);

                  const oldValue = context.getAllControls(nodeId).val;
                  const update = (inputs.dataIn || [])[0] || oldValue;

                  // Update graph if necessary
                  if (update !== oldValue) {
                      await context.updateControl(nodeId, "val", update);
                  }

                  return "triggerOut";
              } catch (error) {
                  console.error("--ERROR--\n", error);
                  return "error";
              }
          },
          async dataFlow(nodeId, context) {
              return {
                  dataOut: context.getAllControls(nodeId).val,
              };
          },
      }
  );
})();