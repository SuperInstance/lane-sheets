"""SuperInstance lane-sheets: agent workflows as sheet data.

One abstraction below LangChain/LangGraph, the way Verilog sits below
C and Python: a workflow is a JSON sheet of lanes and cells, connected
by piping only, whose run state is derived by execution and never
stored in the sheet. See SPEC.md.
"""

__version__ = "0.1"
