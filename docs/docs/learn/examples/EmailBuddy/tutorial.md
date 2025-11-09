# EmailBuddy

EmailBuddy is an agentic AI email assistant built with Jac, a new programming language for creating intelligent agents. It transforms your inbox into a graph-based knowledge system, enabling semantic search, analysis, and RAG-powered navigation through your emails.

## Key Features:

- Summarization & Context Retrieval: Get concise summaries or ask questions about conversations
- Graph-Based Representation: Emails stored as relationships between people and emails
- Web-based Chat Interface: Easy to setup webpage

## Tutorial

In this tutorial, you'll learn how EmailBuddy works under the hood, and why Jac is an ideal language for powering intelligent, graph-driven agents.

This tutorial will NOT go through the entire source code directly. If you want to view the source code checkout the EmailBuddy GitHub repository

### Object-Spatial Programming

#### What is Object-Spatial Programming

Object Spatial Programming (OSP) is a programming paradigm where software logic is expressed and organized using 3D or spatial metaphors rather than only class or functional based code. Instead of writing everything as functions and classes, OSP treats program components as objects placed in space—like nodes, blocks, or agents whose location, proximity, or orientation influences behavior.

#### Why Object-Spatial Programming Fits EmailBuddy

EmailBuddy uses this programming paradigm to structure the relationship between people and their emails. 

We can represent both emails and people as nodes on a graph. Each node can contain information relevant to itself as shown below: 

```Jac
node Person{
    has name: str;
    has email: str;
}

node EmailNode{
    has sender: str;
    has recipients: str;
    has date: str;
    has subject: str;
    has body: str;
    has email_uuid: str;
}
```

Traditional object-oriented programming (OOP) would have similar "classes" to represent this information, however OSP allows for assigning connections between the nodes helps us better understand the relationship between individual nodes. We do this by representing directed edges between a person to an email as a "sender of email" and an email to a person as a "recipient of email"

With this concept we can imagine a scenario where:

- Josh sends an email to John and Sarah
- John sends a response email ONLY to Josh directly

We may imagine a graph like the following below

![Diagram showing how people point to emails (sender) and emails point to people (recipients)](examples/EmailBuddy/assets/EmailBuddy-osp_diagram.png)

#### How EmailBuddy sets up the Object-Spatial graph 

Now that we have a high-level understanding how to represent these Email/People node interactions, how can we actually implement this?

EmailBuddy has two main user-interactions:

1. Upload emails
2. Query chatbot

First we will talk about uploading emails. 

EmailBuddy handles email uploads by allowing users to upload a json file in the following format:

```json
[
  {
    "date": "2025-10-09T06:20:18+00:00",
    "from": "Lily Carter <lcarter@protonmail.com>",
    "to": "Evan Brooks <evan.brooks@gmail.com>",
    "subject": "Hows it going",
    "body": "Hey Evan! We haven't spoken in a while, let's catch up soon."
  }
]
```

These json files are parsed in Jac and are used to create our nodes. We handle node creation by treating our 2 node types (Person & Email) as 3 (Sender, Recipients, & Email). 


For each email uploaded, EmailBuddy:

- Extract sender and recipient addresses
- Create Person nodes if they do not already exist
- Create or skip Email node based on UUID matching
- Connect all Person and Email nodes to the root
- Create directed edges: person → email, and email → recipients


We must connect ALL nodes (Email and Person) to the root node so we can access them later.

??? tip "What is a root node?"
    The root node in Jac acts as a fundamental global pointer on the graph. It is a special node that is always accessible in every request context, especially when running Jac in server mode (jac serve). Think of the root node as the entry point or anchor node that connects to all other nodes in the graph.

    This design ensures that no nodes get "lost" since all nodes are directly or indirectly connected to the root node, making them accessible to the program. This persistent organization facilitates data traversal and manipulation across the graph.

    This is particularly useful for us since every node is connected to root, we can always find any email, even if we don't know who sent it or who received it.


Now that we have all the nodes created (and connected to root) our graph will likely look something like this:

![Emails and Person nodes connected to root but not each other](examples/EmailBuddy/assets/EmailBuddy-osp-unconnected_graph.png)

The issue with this graph is that we don't have any connections between People and Emails

This can be accomplished by something like the following

```Jac
recipientNodes: list[People];
senderNode: People;
emailNode: Email;

senderNode ++> emailNode;
for node in recipientNodes{
    emailNode ++> node;
}
```

With these steps we will have a connected graph representation of our emails for us to traverse.


#### How EmailBuddy uses the graph 

Once our graph is created, we can traverse it using walkers. 

??? tip "What is a walker?" 
  A walker is a program that moves through a Jac graph and executes code at each node.

  A walker is like a little robot that moves through your graph.
  
  As it moves, it can:

  - look at data on a node
  - save information
  - change data
  - create new nodes

  Think of it like a character exploring a map.
  Instead of a function pushing data around, the walker visits the data itself.

EmailBuddy uses a few helper walkers to answer questions like:

- "Does this sender already exist?"
- "Have we seen this email before?"
- "Is this person already in the graph?"

Each helper walker starts at a node (usually the root node) and explores outward until it finds what it needs or reaches the end.

```
(root) → Person → Email → Person
   ↑
 spawn walker here
```


Here’s an example: a walker that starts at root and searches the graph for a Person whose email matches the target.

```Jac
walker FindSenderNode {
    has target: str;
    has person: Person = None;

    can start with `root entry {
        visit [-->];
        return self.person;
    }

    can search with Person entry {
        if here.email == self.target {
            self.person = here;
            disengage;
        }
    }    
}
```

??? tips "Need help with syntax?"
  `has <memberVariable>: <type>`: Create member variables for walker

  `can <attributeName> with <nodeType> entry`: Assigns walker behavior when it is on the node type (root must have `` `root ``)

  `disengage`: Stops the walker immediately so it doesn't keep searching.

  `visit [-->]`: Tells the walker to explore all nodes reachable from this one along outgoing edges.


This walkers goal is to find a specific Person node and return the value. The walker will search through ALL people nodes connected to root until it finds its target or runs out of People to search. If the walker does not find a matching Person node, self.person stays None.

When the FindSenderNode walker is initialized, the walker is passed a target email address as a member variable to find a Person node attached to it. 

```Jac
FindSend = FindSenderNode(target=sender_email);
```

Once the walker is initialized, it behaves just like any other object in OOP: it has member variables and functions you can access. It doesn't actually do anything until we spawn it. Spawning a walker means placing it on a starting node in the graph and letting it run until it reaches its stopping condition. While the walker is active, it can move between nodes and perform actions, such as creating new nodes or modifying existing ones.


We can spawn the walker on root by doing the following command.

```Jac
root spawn FindSend;
```

Once the walker terminates, we can extract the node as follows.

```Jac
sender: Person = FindSend.person;
```
If no matching Person is found, the walker finishes naturally and FindSend.person will still be None.

EmailBuddy has two other helper walkers (FindEmailNode and FindRecipientNodes) that follow a very similar pattern, however the main traversal/query walker (ask_email) works differently. To learn more read about this last walker continue reading about [AI Agents](#ai-agents).

#### Common OSP pitfalls

| Mistake                                 | Symptom                             | Fix                                    |
| --------------------------------------- | ----------------------------------- | -------------------------------------- |
| Forgot to connect nodes to root         | Walker can’t find anything          | `root ++> newNode`                     |
| Email duplicate created twice           | Graph has repeated email nodes      | Check UUID before creation             |
| Walker never stops                      | Infinite graph crawl                | Use `disengage` when end condition met |
| Walker doesn't do anything after spawn  | Attribute undefined for node type   | `can <attrName> with <nodeType> entry` |

### AI Agents

### Scale Native

