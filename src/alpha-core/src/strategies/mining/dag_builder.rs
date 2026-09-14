use std::collections::HashMap;

use super::expression_parser::{hash_ast, AstNode, TsArg};

#[derive(Debug, Clone, PartialEq)]
pub struct DagNode {

    pub id: usize,

    pub ast: AstNode,

    pub dependencies: Vec<usize>,

    pub is_leaf: bool,
}

#[derive(Debug, Clone, Default)]
pub struct ComputationDag {

    pub nodes: Vec<DagNode>,

    pub execution_order: Vec<usize>,

    pub roots: Vec<usize>,
}

impl ComputationDag {

    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }
}

#[derive(Default)]
struct DagInterner {
    nodes: Vec<DagNode>,
    buckets: HashMap<u64, Vec<usize>>,
}

impl DagInterner {

    fn intern(&mut self, ast: &AstNode) -> usize {
        let dependencies = match ast {
            AstNode::Number(_) | AstNode::Field(_) => Vec::new(),
            AstNode::UnaryOp { operand, .. } => vec![self.intern(operand)],
            AstNode::BinaryOp { left, right, .. } => {
                vec![self.intern(left), self.intern(right)]
            }
            AstNode::TsFunc { args, .. } => args
                .iter()
                .map(|arg| match arg {
                    TsArg::Field(name) => self.intern_field(name),
                    TsArg::Expr(inner) => self.intern(inner),
                })
                .collect(),
        };

        let hash = hash_ast(ast);
        if let Some(ids) = self.buckets.get(&hash) {
            for &id in ids {
                if self.nodes[id].ast == *ast {
                    return id;
                }
            }
        }

        let id = self.nodes.len();
        let is_leaf = dependencies.is_empty();
        self.nodes.push(DagNode {
            id,
            ast: ast.clone(),
            dependencies,
            is_leaf,
        });
        self.buckets.entry(hash).or_default().push(id);
        id
    }

    fn intern_field(&mut self, name: &str) -> usize {
        self.intern(&AstNode::Field(name.to_string()))
    }
}

fn topological_order(nodes: &[DagNode]) -> Vec<usize> {

    let mut state = vec![0u8; nodes.len()];
    let mut order = Vec::with_capacity(nodes.len());
    for start in 0..nodes.len() {
        if state[start] != 0 {
            continue;
        }
        let mut stack: Vec<(usize, usize)> = vec![(start, 0)];
        state[start] = 1;
        while let Some(frame) = stack.last_mut() {
            let id = frame.0;
            if frame.1 < nodes[id].dependencies.len() {
                let dep = nodes[id].dependencies[frame.1];
                frame.1 += 1;
                if state[dep] == 0 {
                    state[dep] = 1;
                    stack.push((dep, 0));
                }
            } else {
                state[id] = 2;
                order.push(id);
                stack.pop();
            }
        }
    }
    order
}

pub fn build_dag(asts: &[AstNode]) -> ComputationDag {
    let mut interner = DagInterner::default();
    let roots = asts.iter().map(|ast| interner.intern(ast)).collect();
    let execution_order = topological_order(&interner.nodes);
    ComputationDag {
        nodes: interner.nodes,
        execution_order,
        roots,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::strategies::mining::expression_parser::{parse, BinOp, TsFunc};

    fn dag_for(exprs: &[&str]) -> ComputationDag {
        let asts: Vec<AstNode> = exprs.iter().map(|e| parse(e).expect(e)).collect();
        build_dag(&asts)
    }

    #[test]
    fn empty_input_yields_empty_dag() {
        let dag = build_dag(&[]);
        assert!(dag.is_empty());
        assert!(dag.execution_order.is_empty());
        assert!(dag.roots.is_empty());
    }

    #[test]
    fn shares_common_subexpressions_across_alphas() {
        let dag = dag_for(&[
            "close*close + ts_mean(volume, 5)",
            "close*close - ts_mean(volume, 5)",
        ]);

        assert_eq!(dag.len(), 6);

        let mul = AstNode::BinaryOp {
            op: BinOp::Mul,
            left: Box::new(AstNode::Field("close".into())),
            right: Box::new(AstNode::Field("close".into())),
        };
        let mean = AstNode::TsFunc {
            func: TsFunc::Mean,
            args: vec![super::super::expression_parser::TsArg::Field(
                "volume".into(),
            )],
            window: 5,
            param: 0.0,
        };
        let find = |want: &AstNode| {
            dag.nodes
                .iter()
                .find(|n| &n.ast == want)
                .map(|n| n.id)
                .expect("node must exist exactly once")
        };
        let mul_id = find(&mul);
        let mean_id = find(&mean);

        let (add_root, sub_root) = (dag.roots[0], dag.roots[1]);
        assert_ne!(add_root, sub_root);
        assert_eq!(dag.nodes[add_root].dependencies, vec![mul_id, mean_id]);
        assert_eq!(dag.nodes[sub_root].dependencies, vec![mul_id, mean_id]);

        let close_id = dag.nodes[mul_id].dependencies[0];
        assert!(dag.nodes[close_id].is_leaf);
        assert!(dag.nodes[close_id].dependencies.is_empty());
        assert!(!dag.nodes[add_root].is_leaf);
        assert!(!dag.nodes[mean_id].is_leaf);
    }

    #[test]
    fn identical_alphas_share_their_root_node() {
        let dag = dag_for(&[
            "ts_zscore(ts_mean(close, 8), 480)",
            "ts_zscore(ts_mean(close, 8), 480)",
        ]);

        assert_eq!(dag.len(), 3);
        assert_eq!(dag.roots[0], dag.roots[1]);
    }

    #[test]
    fn execution_order_is_topological_and_complete() {
        let dag = dag_for(&[
            "ts_corr(close/volume, ts_delay(close, 1), 60)",
            "ts_zscore(close/ts_delay(close, 1) - 1.0, 120)",
        ]);

        let mut seen = dag.execution_order.clone();
        seen.sort_unstable();
        assert_eq!(seen, (0..dag.len()).collect::<Vec<_>>());

        let position: Vec<usize> = {
            let mut pos = vec![0usize; dag.len()];
            for (slot, &id) in dag.execution_order.iter().enumerate() {
                pos[id] = slot;
            }
            pos
        };
        for node in &dag.nodes {
            for &dep in &node.dependencies {
                assert!(
                    position[dep] < position[node.id],
                    "dependency {} must precede {}",
                    dep,
                    node.id
                );
            }
        }
    }

    #[test]
    fn root_nodes_match_input_asts_and_constants_are_leaves() {
        let asts = vec![
            parse("close*2").expect("valid"),
            parse("ts_rank(ret, 10)").expect("valid"),
        ];
        let dag = build_dag(&asts);
        assert_eq!(dag.roots.len(), 2);
        for (i, ast) in asts.iter().enumerate() {
            assert_eq!(&dag.nodes[dag.roots[i]].ast, ast);
        }
        assert!(dag
            .nodes
            .iter()
            .any(|n| n.is_leaf && matches!(n.ast, AstNode::Number(_))));
    }
}
