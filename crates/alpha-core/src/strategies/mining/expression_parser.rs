//! Recursive descent parser for the alpha expression DSL.
//!
//! Grammar (whitespace between tokens is insignificant):
//!
//! ```text
//! expr      := term (('+' | '-') term)*
//! term      := factor (('*' | '/') factor)*
//! factor    := number | field | func_call | '(' expr ')' | '-' factor
//! field     := identifier                (close, open, volume, bs_l5_close, ret, ...)
//! func_call := ts_op '(' series_arg (',' series_arg)* ',' window ')'
//!            | cs_op '(' series_arg (',' series_arg)* ')'
//!            | param_op '(' series_arg ',' number (',' window)? ')'
//! ts_op     := ts_mean | ts_std | ts_delta | ts_delay | ts_sum
//!            | ts_rank | ts_corr | ts_zscore | ewma
//!            | ts_min | ts_max | ts_median | ts_quantile | ts_skewness
//!            | ts_kurtosis | ts_ir | ts_product | ts_argmax | ts_argmin
//!            | ts_max_diff | ts_min_diff | ts_scale | ts_quantile_pos
//!            | ts_decay_linear | ts_regression_resid | ts_regression_beta
//!            | ts_covariance | ts_returns | ts_sign_delta | ts_trend_slope
//!            | ts_backfill | ts_count_valid
//! cs_op     := cs_rank | cs_zscore | cs_scale | cs_demean | abs | log
//!            | sign | elem_max | elem_min | if_else
//! window    := strictly positive integer literal
//! ```
//!
//! Conventions:
//! * Windowed time-series functions take one or more series arguments
//!   followed by a strictly positive integer window (or EWMA span) as their
//!   final argument, e.g. `ts_corr(close, volume, 20)`.
//! * `ts_quantile` and `cs_scale` carry an extra numeric constant parameter
//!   placed after the series arguments -- the quantile level in `[0, 1]`
//!   and the absolute-sum target respectively, e.g.
//!   `ts_quantile(close, 0.75, 20)` or `cs_scale(close, 1.0)`.
//! * Cross-sectional / element-wise functions take only series arguments
//!   and no window, e.g. `cs_rank(close)` or `if_else(cond, a, b)`.
//! * A bare identifier passed to a time-series function is captured as
//!   [`TsArg::Field`]; any other expression becomes [`TsArg::Expr`].
//! * Arithmetic is left associative; unary minus binds tighter than `* /`,
//!   which bind tighter than `+ -`. Unary minus never folds into its
//!   operand: `-3.5` parses to `Neg(Number(3.5))`.
//!
//! The parser is std-only. Recursion depth follows AST nesting depth, which
//! in practice is bounded by expression size.

use std::fmt;

// ---------------------------------------------------------------------------
// AST
// ---------------------------------------------------------------------------

/// Abstract syntax node of the alpha DSL.
#[derive(Debug, Clone, PartialEq)]
pub enum AstNode {
    /// Literal floating point constant.
    Number(f64),
    /// Raw data field reference (close, open, volume, bs_l5_close, ret, ...).
    Field(String),
    /// Element-wise binary arithmetic.
    BinaryOp {
        op: BinOp,
        left: Box<AstNode>,
        right: Box<AstNode>,
    },
    /// Unary operator (currently negation only).
    UnaryOp { op: UnaryOp, operand: Box<AstNode> },
    /// Rolling / time-series function application over `window` bars.
    TsFunc {
        func: TsFunc,
        args: Vec<TsArg>,
        window: usize,
        /// Auxiliary scalar constant for functions with a trailing numeric
        /// parameter (`ts_quantile` level, `cs_scale` target). `0.0` for
        /// every other function.
        param: f64,
    },
}

/// Binary arithmetic operators.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
}

impl BinOp {
    /// Infix symbol used by the DSL.
    pub fn symbol(self) -> char {
        match self {
            BinOp::Add => '+',
            BinOp::Sub => '-',
            BinOp::Mul => '*',
            BinOp::Div => '/',
        }
    }
}

/// Unary operators.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnaryOp {
    Neg,
}

/// Functions supported by the DSL: rolling time-series operators (which end
/// in a window argument), plus the cross-sectional / element-wise family
/// (which take no window).
///
/// `Ewma` covers the `ewma` production of the grammar; for it, `window`
/// carries the smoothing span rather than a trailing lookback length.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TsFunc {
    // ----- original rolling operators -------------------------------------
    Mean,
    Std,
    Delta,
    Delay,
    Sum,
    Rank,
    Corr,
    Zscore,
    Ewma,
    // ----- rolling statistics ----------------------------------------------
    /// Rolling minimum (`ts_min`).
    Min,
    /// Rolling maximum (`ts_max`).
    Max,
    /// Rolling median (`ts_median`).
    Median,
    /// Rolling q-th quantile; scalar param = level in [0, 1].
    Quantile,
    /// Rolling standardised third moment (`ts_skewness`).
    Skewness,
    /// Rolling excess kurtosis (`ts_kurtosis`).
    Kurtosis,
    /// Rolling information ratio mean/std (`ts_ir`).
    Ir,
    /// Rolling product with zero handling (`ts_product`).
    Product,
    // ----- positioning and distance ----------------------------------------
    /// Bars since window maximum (`ts_argmax`).
    ArgMax,
    /// Bars since window minimum (`ts_argmin`).
    ArgMin,
    /// Current minus window maximum (`ts_max_diff`).
    MaxDiff,
    /// Current minus window minimum (`ts_min_diff`).
    MinDiff,
    /// Min-max normalisation to [0, 1] (`ts_scale`).
    Scale,
    /// Fraction of window strictly below current value
    /// (`ts_quantile_pos`).
    QuantilePos,
    // ----- decay ------------------------------------------------------------
    /// Linearly decaying weighted average (`ts_decay_linear`).
    DecayLinear,
    // ----- regression and relationship --------------------------------------
    /// OLS residual at current bar (`ts_regression_resid`, 2 series args).
    RegressionResid,
    /// OLS slope coefficient (`ts_regression_beta`, 2 series args).
    RegressionBeta,
    /// Rolling sample covariance ddof=1 (`ts_covariance`, 2 series args).
    Covariance,
    // ----- momentum and returns ---------------------------------------------
    /// Percentage change vs d bars ago (`ts_returns`).
    Returns,
    /// Sign of net change over d bars (`ts_sign_delta`).
    SignDelta,
    /// OLS slope against bar index (`ts_trend_slope`).
    TrendSlope,
    // ----- utility ------------------------------------------------------------
    /// Fill NaN from up to d bars back (`ts_backfill`).
    Backfill,
    /// Non-NaN count in trailing window (`ts_count_valid`).
    CountValid,
    // ----- cross-sectional / element-wise (no window) -----------------------
    /// Cross-sectional rank normalised to (0, 1] with averaged ties.
    CsRank,
    /// Cross-sectional population z-score over valid entries.
    CsZscore,
    /// Rescale so absolute values sum to the scalar param target.
    CsScale,
    /// Subtract cross-sectional mean of valid entries.
    CsDemean,
    /// Element-wise absolute value (`abs`).
    Abs,
    /// Element-wise natural log; NaN for x <= 0 (`log`).
    Log,
    /// Element-wise sign in {-1, 0, +1} (`sign`).
    Sign,
    /// Element-wise maximum, NaN-propagating (`elem_max`, 2 args).
    ElemMax,
    /// Element-wise minimum, NaN-propagating (`elem_min`, 2 args).
    ElemMin,
    /// Element-wise conditional selection (`if_else`, 3 args).
    IfElse,
}

impl TsFunc {
    /// Number of series arguments required (window and scalar parameter
    /// arguments excluded).
    pub fn arity(self) -> usize {
        match self {
            TsFunc::Corr
            | TsFunc::RegressionResid
            | TsFunc::RegressionBeta
            | TsFunc::Covariance
            | TsFunc::ElemMax
            | TsFunc::ElemMin => 2,
            TsFunc::IfElse => 3,
            _ => 1,
        }
    }

    /// DSL name of the function.
    pub fn name(self) -> &'static str {
        match self {
            TsFunc::Mean => "ts_mean",
            TsFunc::Std => "ts_std",
            TsFunc::Delta => "ts_delta",
            TsFunc::Delay => "ts_delay",
            TsFunc::Sum => "ts_sum",
            TsFunc::Rank => "ts_rank",
            TsFunc::Corr => "ts_corr",
            TsFunc::Zscore => "ts_zscore",
            TsFunc::Ewma => "ewma",
            TsFunc::Min => "ts_min",
            TsFunc::Max => "ts_max",
            TsFunc::Median => "ts_median",
            TsFunc::Quantile => "ts_quantile",
            TsFunc::Skewness => "ts_skewness",
            TsFunc::Kurtosis => "ts_kurtosis",
            TsFunc::Ir => "ts_ir",
            TsFunc::Product => "ts_product",
            TsFunc::ArgMax => "ts_argmax",
            TsFunc::ArgMin => "ts_argmin",
            TsFunc::MaxDiff => "ts_max_diff",
            TsFunc::MinDiff => "ts_min_diff",
            TsFunc::Scale => "ts_scale",
            TsFunc::QuantilePos => "ts_quantile_pos",
            TsFunc::DecayLinear => "ts_decay_linear",
            TsFunc::RegressionResid => "ts_regression_resid",
            TsFunc::RegressionBeta => "ts_regression_beta",
            TsFunc::Covariance => "ts_covariance",
            TsFunc::Returns => "ts_returns",
            TsFunc::SignDelta => "ts_sign_delta",
            TsFunc::TrendSlope => "ts_trend_slope",
            TsFunc::Backfill => "ts_backfill",
            TsFunc::CountValid => "ts_count_valid",
            TsFunc::CsRank => "cs_rank",
            TsFunc::CsZscore => "cs_zscore",
            TsFunc::CsScale => "cs_scale",
            TsFunc::CsDemean => "cs_demean",
            TsFunc::Abs => "abs",
            TsFunc::Log => "log",
            TsFunc::Sign => "sign",
            TsFunc::ElemMax => "elem_max",
            TsFunc::ElemMin => "elem_min",
            TsFunc::IfElse => "if_else",
        }
    }

    fn from_name(name: &str) -> Option<TsFunc> {
        match name {
            "ts_mean" => Some(TsFunc::Mean),
            "ts_std" => Some(TsFunc::Std),
            "ts_delta" => Some(TsFunc::Delta),
            "ts_delay" => Some(TsFunc::Delay),
            "ts_sum" => Some(TsFunc::Sum),
            "ts_rank" => Some(TsFunc::Rank),
            "ts_corr" => Some(TsFunc::Corr),
            "ts_zscore" => Some(TsFunc::Zscore),
            "ewma" => Some(TsFunc::Ewma),
            "ts_min" => Some(TsFunc::Min),
            "ts_max" => Some(TsFunc::Max),
            "ts_median" => Some(TsFunc::Median),
            "ts_quantile" => Some(TsFunc::Quantile),
            "ts_skewness" => Some(TsFunc::Skewness),
            "ts_kurtosis" => Some(TsFunc::Kurtosis),
            "ts_ir" => Some(TsFunc::Ir),
            "ts_product" => Some(TsFunc::Product),
            "ts_argmax" => Some(TsFunc::ArgMax),
            "ts_argmin" => Some(TsFunc::ArgMin),
            "ts_max_diff" => Some(TsFunc::MaxDiff),
            "ts_min_diff" => Some(TsFunc::MinDiff),
            "ts_scale" => Some(TsFunc::Scale),
            "ts_quantile_pos" => Some(TsFunc::QuantilePos),
            "ts_decay_linear" => Some(TsFunc::DecayLinear),
            "ts_regression_resid" => Some(TsFunc::RegressionResid),
            "ts_regression_beta" => Some(TsFunc::RegressionBeta),
            "ts_covariance" => Some(TsFunc::Covariance),
            "ts_returns" => Some(TsFunc::Returns),
            "ts_sign_delta" => Some(TsFunc::SignDelta),
            "ts_trend_slope" => Some(TsFunc::TrendSlope),
            "ts_backfill" => Some(TsFunc::Backfill),
            "ts_count_valid" => Some(TsFunc::CountValid),
            "cs_rank" => Some(TsFunc::CsRank),
            "cs_zscore" => Some(TsFunc::CsZscore),
            "cs_scale" => Some(TsFunc::CsScale),
            "cs_demean" => Some(TsFunc::CsDemean),
            "abs" => Some(TsFunc::Abs),
            "log" => Some(TsFunc::Log),
            "sign" => Some(TsFunc::Sign),
            "elem_max" => Some(TsFunc::ElemMax),
            "elem_min" => Some(TsFunc::ElemMin),
            "if_else" => Some(TsFunc::IfElse),
            _ => None,
        }
    }

    /// True when the DSL form ends with a strictly positive integer window
    /// argument. False for the cross-sectional / element-wise family.
    pub fn windowed(self) -> bool {
        matches!(
            self,
            TsFunc::Mean
                | TsFunc::Std
                | TsFunc::Delta
                | TsFunc::Delay
                | TsFunc::Sum
                | TsFunc::Rank
                | TsFunc::Corr
                | TsFunc::Zscore
                | TsFunc::Ewma
                | TsFunc::Min
                | TsFunc::Max
                | TsFunc::Median
                | TsFunc::Quantile
                | TsFunc::Skewness
                | TsFunc::Kurtosis
                | TsFunc::Ir
                | TsFunc::Product
                | TsFunc::ArgMax
                | TsFunc::ArgMin
                | TsFunc::MaxDiff
                | TsFunc::MinDiff
                | TsFunc::Scale
                | TsFunc::QuantilePos
                | TsFunc::DecayLinear
                | TsFunc::RegressionResid
                | TsFunc::RegressionBeta
                | TsFunc::Covariance
                | TsFunc::Returns
                | TsFunc::SignDelta
                | TsFunc::TrendSlope
                | TsFunc::Backfill
                | TsFunc::CountValid
        )
    }

    /// Description of the mandatory numeric constant parameter for functions
    /// that carry one (placed after the series arguments); `None` otherwise.
    pub fn scalar_param(self) -> Option<&'static str> {
        match self {
            TsFunc::Quantile => Some("a quantile level between 0.0 and 1.0"),
            TsFunc::CsScale => Some("a finite target for the sum of absolute values"),
            _ => None,
        }
    }
}

/// Argument of a time-series function.
#[derive(Debug, Clone, PartialEq)]
pub enum TsArg {
    /// Bare data field reference.
    Field(String),
    /// Arbitrary nested expression.
    Expr(Box<AstNode>),
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// Parse failure with source position (byte offset) where available.
#[derive(Debug, Clone, PartialEq)]
pub enum ParseError {
    /// Input ended while an expression was still expected.
    UnexpectedEof,
    /// A character outside the DSL alphabet.
    UnknownSymbol { ch: char, pos: usize },
    /// A numeric literal that failed to parse (e.g. `1e`).
    MalformedNumber { text: String, pos: usize },
    /// A token that cannot continue the current production.
    UnexpectedToken {
        found: String,
        pos: usize,
        expected: &'static str,
    },
    /// Identifier followed by `(` that is not a known time-series function.
    UnknownFunction { name: String, pos: usize },
    /// Function call without any arguments.
    MissingArguments { func: &'static str, pos: usize },
    /// Wrong number of series arguments for the function.
    WrongArity {
        func: &'static str,
        expected: &'static str,
        got: usize,
        pos: usize,
    },
    /// Final argument is not a strictly positive integer window.
    InvalidWindow { func: &'static str, pos: usize },
    /// A function's numeric parameter (quantile level, scale target) is
    /// missing, not a literal number, or outside its valid range.
    InvalidParam {
        func: &'static str,
        expected: &'static str,
        pos: usize,
    },
    /// Complete expression parsed but tokens remain.
    TrailingInput { pos: usize },
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseError::UnexpectedEof => write!(f, "unexpected end of input"),
            ParseError::UnknownSymbol { ch, pos } => {
                write!(f, "unknown symbol '{}' at byte {}", ch, pos)
            }
            ParseError::MalformedNumber { text, pos } => {
                write!(f, "malformed number '{}' at byte {}", text, pos)
            }
            ParseError::UnexpectedToken {
                found,
                pos,
                expected,
            } => write!(
                f,
                "unexpected {} at byte {}, expected {}",
                found, pos, expected
            ),
            ParseError::UnknownFunction { name, pos } => {
                write!(f, "unknown function '{}' at byte {}", name, pos)
            }
            ParseError::MissingArguments { func, pos } => {
                write!(f, "{} called without arguments at byte {}", func, pos)
            }
            ParseError::WrongArity {
                func,
                expected,
                got,
                pos,
            } => write!(
                f,
                "{} expects {}, got {} series argument(s) at byte {}",
                func, expected, got, pos
            ),
            ParseError::InvalidWindow { func, pos } => write!(
                f,
                "{} requires a strictly positive integer window argument at byte {}",
                func, pos
            ),
            ParseError::InvalidParam {
                func,
                expected,
                pos,
            } => write!(
                f,
                "{} requires {} as its numeric parameter at byte {}",
                func, expected, pos
            ),
            ParseError::TrailingInput { pos } => {
                write!(
                    f,
                    "unexpected input after complete expression at byte {}",
                    pos
                )
            }
        }
    }
}

impl std::error::Error for ParseError {}

// ---------------------------------------------------------------------------
// Lexer
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
enum TokKind {
    Num(f64),
    Ident(String),
    Plus,
    Minus,
    Star,
    Slash,
    LParen,
    RParen,
    Comma,
}

#[derive(Debug, Clone, PartialEq)]
struct Token {
    kind: TokKind,
    pos: usize,
}

fn describe(kind: &TokKind) -> String {
    match kind {
        TokKind::Num(v) => format!("number '{}'", v),
        TokKind::Ident(name) => format!("identifier '{}'", name),
        TokKind::Plus => "'+'".to_string(),
        TokKind::Minus => "'-'".to_string(),
        TokKind::Star => "'*'".to_string(),
        TokKind::Slash => "'/'".to_string(),
        TokKind::LParen => "'('".to_string(),
        TokKind::RParen => "')'".to_string(),
        TokKind::Comma => "','".to_string(),
    }
}

fn lex_number(input: &str, bytes: &[u8], start: usize) -> Result<(Token, usize), ParseError> {
    let mut i = start;
    while i < bytes.len() && bytes[i].is_ascii_digit() {
        i += 1;
    }
    if i < bytes.len() && bytes[i] == b'.' {
        i += 1;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            i += 1;
        }
    }
    if i < bytes.len() && (bytes[i] == b'e' || bytes[i] == b'E') {
        let mut j = i + 1;
        if j < bytes.len() && (bytes[j] == b'+' || bytes[j] == b'-') {
            j += 1;
        }
        if j < bytes.len() && bytes[j].is_ascii_digit() {
            while j < bytes.len() && bytes[j].is_ascii_digit() {
                j += 1;
            }
            i = j;
        } else {
            return Err(ParseError::MalformedNumber {
                text: input[start..j.min(input.len())].to_string(),
                pos: start,
            });
        }
    }
    let text = &input[start..i];
    let value = text
        .parse::<f64>()
        .map_err(|_| ParseError::MalformedNumber {
            text: text.to_string(),
            pos: start,
        })?;
    Ok((
        Token {
            kind: TokKind::Num(value),
            pos: start,
        },
        i,
    ))
}

fn tokenize(input: &str) -> Result<Vec<Token>, ParseError> {
    let bytes = input.as_bytes();
    let mut toks = Vec::new();
    let mut i = 0usize;
    while i < bytes.len() {
        let b = bytes[i];
        match b {
            b' ' | b'\t' | b'\r' | b'\n' => i += 1,
            b'+' => {
                toks.push(Token {
                    kind: TokKind::Plus,
                    pos: i,
                });
                i += 1;
            }
            b'-' => {
                toks.push(Token {
                    kind: TokKind::Minus,
                    pos: i,
                });
                i += 1;
            }
            b'*' => {
                toks.push(Token {
                    kind: TokKind::Star,
                    pos: i,
                });
                i += 1;
            }
            b'/' => {
                toks.push(Token {
                    kind: TokKind::Slash,
                    pos: i,
                });
                i += 1;
            }
            b'(' => {
                toks.push(Token {
                    kind: TokKind::LParen,
                    pos: i,
                });
                i += 1;
            }
            b')' => {
                toks.push(Token {
                    kind: TokKind::RParen,
                    pos: i,
                });
                i += 1;
            }
            b',' => {
                toks.push(Token {
                    kind: TokKind::Comma,
                    pos: i,
                });
                i += 1;
            }
            b'0'..=b'9' => {
                let (tok, next) = lex_number(input, bytes, i)?;
                toks.push(tok);
                i = next;
            }
            b'_' | b'a'..=b'z' | b'A'..=b'Z' => {
                let start = i;
                while i < bytes.len() && (bytes[i] == b'_' || bytes[i].is_ascii_alphanumeric()) {
                    i += 1;
                }
                toks.push(Token {
                    kind: TokKind::Ident(input[start..i].to_string()),
                    pos: start,
                });
            }
            _ => {
                let ch = input[i..].chars().next().unwrap_or('?');
                return Err(ParseError::UnknownSymbol { ch, pos: i });
            }
        }
    }
    Ok(toks)
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

struct Parser {
    toks: Vec<Token>,
    idx: usize,
}

impl Parser {
    fn peek(&self) -> Option<&Token> {
        self.toks.get(self.idx)
    }

    fn peek_kind(&self) -> Option<&TokKind> {
        self.toks.get(self.idx).map(|t| &t.kind)
    }

    fn peek_second(&self) -> Option<&TokKind> {
        self.toks.get(self.idx + 1).map(|t| &t.kind)
    }

    fn bump(&mut self) -> Option<Token> {
        let tok = self.toks.get(self.idx).cloned();
        if tok.is_some() {
            self.idx += 1;
        }
        tok
    }

    fn err_unexpected(&self, expected: &'static str) -> ParseError {
        match self.toks.get(self.idx) {
            Some(t) => ParseError::UnexpectedToken {
                found: describe(&t.kind),
                pos: t.pos,
                expected,
            },
            None => ParseError::UnexpectedEof,
        }
    }

    // expr := term (('+' | '-') term)*
    fn parse_expr(&mut self) -> Result<AstNode, ParseError> {
        let mut lhs = self.parse_term()?;
        loop {
            let op = match self.peek_kind() {
                Some(TokKind::Plus) => BinOp::Add,
                Some(TokKind::Minus) => BinOp::Sub,
                _ => break,
            };
            self.idx += 1;
            let rhs = self.parse_term()?;
            lhs = AstNode::BinaryOp {
                op,
                left: Box::new(lhs),
                right: Box::new(rhs),
            };
        }
        Ok(lhs)
    }

    // term := factor (('*' | '/') factor)*
    fn parse_term(&mut self) -> Result<AstNode, ParseError> {
        let mut lhs = self.parse_factor()?;
        loop {
            let op = match self.peek_kind() {
                Some(TokKind::Star) => BinOp::Mul,
                Some(TokKind::Slash) => BinOp::Div,
                _ => break,
            };
            self.idx += 1;
            let rhs = self.parse_factor()?;
            lhs = AstNode::BinaryOp {
                op,
                left: Box::new(lhs),
                right: Box::new(rhs),
            };
        }
        Ok(lhs)
    }

    // factor := number | field | func_call | '(' expr ')' | '-' factor
    fn parse_factor(&mut self) -> Result<AstNode, ParseError> {
        let tok = match self.peek() {
            Some(t) => t.clone(),
            None => return Err(ParseError::UnexpectedEof),
        };
        match tok.kind {
            TokKind::Num(v) => {
                self.idx += 1;
                Ok(AstNode::Number(v))
            }
            TokKind::Minus => {
                self.idx += 1;
                let operand = self.parse_factor()?;
                Ok(AstNode::UnaryOp {
                    op: UnaryOp::Neg,
                    operand: Box::new(operand),
                })
            }
            TokKind::LParen => {
                self.idx += 1;
                let inner = self.parse_expr()?;
                match self.bump() {
                    Some(t) if t.kind == TokKind::RParen => Ok(inner),
                    _ => Err(self.err_unexpected("')'")),
                }
            }
            TokKind::Ident(name) => {
                let looks_like_call = matches!(self.peek_second(), Some(TokKind::LParen));
                if looks_like_call {
                    match TsFunc::from_name(&name) {
                        Some(func) => {
                            self.idx += 2; // consume identifier and '('
                            self.parse_call(func, tok.pos)
                        }
                        None => Err(ParseError::UnknownFunction { name, pos: tok.pos }),
                    }
                } else {
                    self.idx += 1;
                    Ok(AstNode::Field(name))
                }
            }
            other => Err(ParseError::UnexpectedToken {
                found: describe(&other),
                pos: tok.pos,
                expected: "a number, field, function call, '(' or '-'",
            }),
        }
    }

    // func_call body. Windowed functions take series args followed by a
    // strictly positive integer window; functions with a scalar parameter
    // take that constant after the series args (before the window);
    // cross-sectional / element-wise functions take series args only.
    // The opening '(' has already been consumed by the caller.
    fn parse_call(&mut self, func: TsFunc, call_pos: usize) -> Result<AstNode, ParseError> {
        if matches!(self.peek_kind(), Some(TokKind::RParen)) {
            return Err(ParseError::MissingArguments {
                func: func.name(),
                pos: call_pos,
            });
        }
        let mut parsed: Vec<(AstNode, usize)> = Vec::with_capacity(4);
        loop {
            let arg_start = self.peek().map(|t| t.pos).unwrap_or(call_pos);
            let expr = self.parse_expr()?;
            parsed.push((expr, arg_start));
            match self.peek_kind() {
                Some(TokKind::Comma) => self.idx += 1,
                Some(TokKind::RParen) => {
                    self.idx += 1;
                    break;
                }
                _ => return Err(self.err_unexpected("',' or ')'")),
            }
        }

        // Windowed functions end in the window literal.
        let mut window = 0usize;
        if func.windowed() {
            let (last_expr, last_pos) = parsed.pop().expect("at least one parsed argument");
            window = match &last_expr {
                AstNode::Number(v)
                    if v.is_finite()
                        && v.fract() == 0.0
                        && *v >= 1.0
                        && *v <= usize::MAX as f64 =>
                {
                    *v as usize
                }
                _ => {
                    return Err(ParseError::InvalidWindow {
                        func: func.name(),
                        pos: last_pos,
                    })
                }
            };
        }

        // Functions with a scalar parameter consume it next (it is the last
        // remaining argument at this point).
        let mut param = 0.0f64;
        if let Some(expected) = func.scalar_param() {
            let (param_expr, param_pos) = match parsed.pop() {
                Some(pair) => pair,
                None => {
                    return Err(ParseError::InvalidParam {
                        func: func.name(),
                        expected,
                        pos: call_pos,
                    })
                }
            };
            let value = match param_expr {
                AstNode::Number(v) if v.is_finite() => v,
                _ => {
                    return Err(ParseError::InvalidParam {
                        func: func.name(),
                        expected,
                        pos: param_pos,
                    })
                }
            };
            let in_range = match func {
                TsFunc::Quantile => (0.0..=1.0).contains(&value),
                _ => true,
            };
            if !in_range {
                return Err(ParseError::InvalidParam {
                    func: func.name(),
                    expected,
                    pos: param_pos,
                });
            }
            param = value;
        }

        let n_series = parsed.len();
        if n_series != func.arity() {
            return Err(ParseError::WrongArity {
                func: func.name(),
                expected: match func.arity() {
                    2 => "exactly 2 series arguments",
                    3 => "exactly 3 series arguments",
                    _ => "exactly 1 series argument",
                },
                got: n_series,
                pos: call_pos,
            });
        }

        let args = parsed
            .into_iter()
            .map(|(expr, _)| match expr {
                AstNode::Field(name) => TsArg::Field(name),
                other => TsArg::Expr(Box::new(other)),
            })
            .collect();

        Ok(AstNode::TsFunc {
            func,
            args,
            window,
            param,
        })
    }
}

/// Parse an alpha expression into an [`AstNode`].
///
/// The whole input must form exactly one expression; leftover tokens yield
/// [`ParseError::TrailingInput`].
pub fn parse(input: &str) -> Result<AstNode, ParseError> {
    let toks = tokenize(input)?;
    if toks.is_empty() {
        return Err(ParseError::UnexpectedEof);
    }
    let mut parser = Parser { toks, idx: 0 };
    let ast = parser.parse_expr()?;
    if parser.idx != parser.toks.len() {
        return Err(ParseError::TrailingInput {
            pos: parser.toks[parser.idx].pos,
        });
    }
    Ok(ast)
}

// ---------------------------------------------------------------------------
// AST utilities
// ---------------------------------------------------------------------------

/// Collect all data field names referenced by `ast`, deduplicated, in
/// first-appearance (pre-order) order.
pub fn collect_fields(ast: &AstNode) -> Vec<String> {
    let mut out = Vec::new();
    collect_into(ast, &mut out);
    out
}

fn collect_into(ast: &AstNode, out: &mut Vec<String>) {
    match ast {
        AstNode::Number(_) => {}
        AstNode::Field(name) => {
            if !out.contains(name) {
                out.push(name.clone());
            }
        }
        AstNode::BinaryOp { left, right, .. } => {
            collect_into(left, out);
            collect_into(right, out);
        }
        AstNode::UnaryOp { operand, .. } => collect_into(operand, out),
        AstNode::TsFunc { args, .. } => {
            for arg in args {
                match arg {
                    TsArg::Field(name) => {
                        if !out.contains(name) {
                            out.push(name.clone());
                        }
                    }
                    TsArg::Expr(inner) => collect_into(inner, out),
                }
            }
        }
    }
}

const TAG_NUMBER: u8 = 1;
const TAG_FIELD: u8 = 2;
const TAG_BINARY: u8 = 3;
const TAG_UNARY: u8 = 4;
const TAG_TS: u8 = 5;
const ARG_FIELD: u8 = 6;
const ARG_EXPR: u8 = 7;

/// Deterministic FNV-1a 64-bit hasher used by [`hash_ast`].
struct Fnv {
    state: u64,
}

impl Fnv {
    fn new() -> Self {
        Fnv {
            state: 0xcbf2_9ce4_8422_2325,
        }
    }

    fn byte(&mut self, b: u8) {
        self.state ^= b as u64;
        self.state = self.state.wrapping_mul(0x100_0000_01b3);
    }

    fn bytes(&mut self, data: &[u8]) {
        for &b in data {
            self.byte(b);
        }
    }

    fn u64(&mut self, v: u64) {
        self.bytes(&v.to_le_bytes());
    }

    fn usz(&mut self, v: usize) {
        self.u64(v as u64);
    }
}

fn hash_into(ast: &AstNode, h: &mut Fnv) {
    match ast {
        AstNode::Number(v) => {
            h.byte(TAG_NUMBER);
            // Canonicalize negative zero so 0.0 and -0.0 land in the same
            // hash bucket (they compare equal via PartialEq).
            let canonical = if *v == 0.0 { 0.0f64 } else { *v };
            h.u64(canonical.to_bits());
        }
        AstNode::Field(name) => {
            h.byte(TAG_FIELD);
            h.usz(name.len());
            h.bytes(name.as_bytes());
        }
        AstNode::BinaryOp { op, left, right } => {
            h.byte(TAG_BINARY);
            h.byte(*op as u8);
            hash_into(left, h);
            hash_into(right, h);
        }
        AstNode::UnaryOp { op, operand } => {
            h.byte(TAG_UNARY);
            h.byte(*op as u8);
            hash_into(operand, h);
        }
        AstNode::TsFunc {
            func,
            args,
            window,
            param,
        } => {
            h.byte(TAG_TS);
            h.byte(*func as u8);
            h.usz(*window);
            // Canonicalize negative zero so +/-0.0 params hash identically
            // (they compare equal via PartialEq).
            let canonical_param = if *param == 0.0 { 0.0f64 } else { *param };
            h.u64(canonical_param.to_bits());
            h.usz(args.len());
            for arg in args {
                match arg {
                    TsArg::Field(name) => {
                        h.byte(ARG_FIELD);
                        h.usz(name.len());
                        h.bytes(name.as_bytes());
                    }
                    TsArg::Expr(inner) => {
                        h.byte(ARG_EXPR);
                        hash_into(inner, h);
                    }
                }
            }
        }
    }
}

/// Deterministic structural hash of an AST, used to bucket candidate
/// duplicates during DAG construction. Identical trees always produce equal
/// hashes; different trees usually differ. Callers must confirm equality
/// separately (see `dag_builder`).
pub fn hash_ast(ast: &AstNode) -> u64 {
    let mut h = Fnv::new();
    hash_into(ast, &mut h);
    h.state
}

// ---------------------------------------------------------------------------
// Display (canonical printer)
// ---------------------------------------------------------------------------

const PREC_ADD: u8 = 2;
const PREC_MUL: u8 = 3;
const PREC_UNARY: u8 = 4;
const PREC_ATOM: u8 = 5;

fn prec_of(node: &AstNode) -> u8 {
    match node {
        AstNode::Number(_) | AstNode::Field(_) | AstNode::TsFunc { .. } => PREC_ATOM,
        AstNode::UnaryOp { .. } => PREC_UNARY,
        AstNode::BinaryOp { op, .. } => match op {
            BinOp::Mul | BinOp::Div => PREC_MUL,
            BinOp::Add | BinOp::Sub => PREC_ADD,
        },
    }
}

/// Render `ast` back to DSL source. For any AST produced by [`parse`],
/// `parse(&ast.to_string())` returns a structurally identical tree.
/// (Hand-built trees that wrap a bare field in `TsArg::Expr` print as a bare
/// field and therefore re-parse to `TsArg::Field`.)
impl fmt::Display for AstNode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mut out = String::new();
        emit(self, &mut out);
        f.write_str(&out)
    }
}

fn emit(node: &AstNode, out: &mut String) {
    match node {
        AstNode::Number(v) => out.push_str(&format!("{:?}", v)),
        AstNode::Field(name) => out.push_str(name),
        AstNode::UnaryOp { operand, .. } => {
            out.push('-');
            wrap_emit(operand, PREC_UNARY, false, out);
        }
        AstNode::BinaryOp { op, left, right } => {
            let p = prec_of(node);
            wrap_emit(left, p, false, out);
            out.push(op.symbol());
            wrap_emit(right, p, true, out);
        }
        AstNode::TsFunc {
            func,
            args,
            window,
            param,
        } => {
            out.push_str(func.name());
            out.push('(');
            for (i, arg) in args.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                match arg {
                    TsArg::Field(name) => out.push_str(name),
                    TsArg::Expr(inner) => wrap_emit(inner, PREC_UNARY, false, out),
                }
            }
            // The scalar parameter sits between the series args and the
            // window so its printed form re-parses to the same position.
            if func.scalar_param().is_some() {
                out.push(',');
                out.push_str(&format!("{:?}", param));
            }
            if func.windowed() {
                out.push(',');
                out.push_str(&window.to_string());
            }
            out.push(')');
        }
    }
}

fn wrap_emit(child: &AstNode, parent_prec: u8, right_slot: bool, out: &mut String) {
    let child_prec = prec_of(child);
    // Right operands need parentheses on ties so left associativity survives
    // printing: `a-(b+c)` must not become `a-b+c`.
    let needs_parens = if right_slot {
        child_prec <= parent_prec
    } else {
        child_prec < parent_prec
    };
    if needs_parens {
        out.push('(');
        emit(child, out);
        out.push(')');
    } else {
        emit(child, out);
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn f(name: &str) -> AstNode {
        AstNode::Field(name.to_string())
    }

    fn num(v: f64) -> AstNode {
        AstNode::Number(v)
    }

    fn bin(op: BinOp, l: AstNode, r: AstNode) -> AstNode {
        AstNode::BinaryOp {
            op,
            left: Box::new(l),
            right: Box::new(r),
        }
    }

    fn neg(e: AstNode) -> AstNode {
        AstNode::UnaryOp {
            op: UnaryOp::Neg,
            operand: Box::new(e),
        }
    }

    fn ts(func: TsFunc, args: Vec<TsArg>, window: usize) -> AstNode {
        AstNode::TsFunc {
            func,
            args,
            window,
            param: 0.0,
        }
    }

    fn ts_param(func: TsFunc, args: Vec<TsArg>, param: f64, window: usize) -> AstNode {
        AstNode::TsFunc {
            func,
            args,
            window,
            param,
        }
    }

    fn fld_arg(name: &str) -> TsArg {
        TsArg::Field(name.to_string())
    }

    #[test]
    fn atoms_parse_to_field_and_number_nodes() {
        assert_eq!(parse("close"), Ok(f("close")));
        assert_eq!(parse("  42 "), Ok(num(42.0)));
        assert_eq!(parse("bs_l5_close"), Ok(f("bs_l5_close")));
        assert_eq!(parse("_hidden1"), Ok(f("_hidden1")));
    }

    #[test]
    fn precedence_and_left_associativity() {
        assert_eq!(
            parse("close+open*volume"),
            Ok(bin(
                BinOp::Add,
                f("close"),
                bin(BinOp::Mul, f("open"), f("volume"))
            ))
        );
        assert_eq!(
            parse("close-open-volume"),
            Ok(bin(
                BinOp::Sub,
                bin(BinOp::Sub, f("close"), f("open")),
                f("volume")
            ))
        );
        assert_eq!(
            parse("(close+open)*volume"),
            Ok(bin(
                BinOp::Mul,
                bin(BinOp::Add, f("close"), f("open")),
                f("volume")
            ))
        );
        assert_eq!(
            parse("a/b/c"),
            Ok(bin(BinOp::Div, bin(BinOp::Div, f("a"), f("b")), f("c")))
        );
        assert_eq!(
            parse("a-(b-c)"),
            Ok(bin(BinOp::Sub, f("a"), bin(BinOp::Sub, f("b"), f("c"))))
        );
    }

    #[test]
    fn unary_minus_binds_tighter_than_mul_div() {
        assert_eq!(
            parse("-close*volume"),
            Ok(bin(BinOp::Mul, neg(f("close")), f("volume")))
        );
        assert_eq!(
            parse("-(close+open)"),
            Ok(neg(bin(BinOp::Add, f("close"), f("open"))))
        );
        assert_eq!(parse("--ret"), Ok(neg(neg(f("ret")))));
        assert_eq!(parse("-3.5"), Ok(neg(num(3.5))));
    }

    #[test]
    fn ts_functions_parse_with_window_last() {
        assert_eq!(
            parse("ts_mean(close, 20)"),
            Ok(ts(TsFunc::Mean, vec![fld_arg("close")], 20))
        );
        assert_eq!(
            parse("ts_mean(ts_delta(close, 1), 10)"),
            Ok(ts(
                TsFunc::Mean,
                vec![TsArg::Expr(Box::new(ts(
                    TsFunc::Delta,
                    vec![fld_arg("close")],
                    1
                )))],
                10
            ))
        );
        assert_eq!(
            parse("ts_corr(close, volume, 60)"),
            Ok(ts(
                TsFunc::Corr,
                vec![fld_arg("close"), fld_arg("volume")],
                60
            ))
        );
        assert_eq!(
            parse("ts_rank(close/open, 12)"),
            Ok(ts(
                TsFunc::Rank,
                vec![TsArg::Expr(Box::new(bin(
                    BinOp::Div,
                    f("close"),
                    f("open")
                )))],
                12
            ))
        );
        assert_eq!(
            parse("ewma(ret, 8)"),
            Ok(ts(TsFunc::Ewma, vec![fld_arg("ret")], 8))
        );
    }

    #[test]
    fn new_windowed_operators_parse_with_arity_and_param() {
        // Single-series windowed operators: (source, variant, series field).
        for (src, func, field) in [
            ("ts_min(close, 5)", TsFunc::Min, "close"),
            ("ts_max(close, 5)", TsFunc::Max, "close"),
            ("ts_median(close, 21)", TsFunc::Median, "close"),
            ("ts_skewness(ret, 60)", TsFunc::Skewness, "ret"),
            ("ts_kurtosis(ret, 90)", TsFunc::Kurtosis, "ret"),
            ("ts_ir(ret, 30)", TsFunc::Ir, "ret"),
            ("ts_product(volume, 10)", TsFunc::Product, "volume"),
            ("ts_argmax(close, 14)", TsFunc::ArgMax, "close"),
            ("ts_argmin(close, 14)", TsFunc::ArgMin, "close"),
            ("ts_max_diff(close, 20)", TsFunc::MaxDiff, "close"),
            ("ts_min_diff(close, 20)", TsFunc::MinDiff, "close"),
            ("ts_scale(close, 9)", TsFunc::Scale, "close"),
            ("ts_quantile_pos(close, 12)", TsFunc::QuantilePos, "close"),
            ("ts_decay_linear(close, 15)", TsFunc::DecayLinear, "close"),
            ("ts_returns(close, 1)", TsFunc::Returns, "close"),
            ("ts_sign_delta(ret, 5)", TsFunc::SignDelta, "ret"),
            ("ts_trend_slope(close, 22)", TsFunc::TrendSlope, "close"),
            ("ts_backfill(close, 3)", TsFunc::Backfill, "close"),
            ("ts_count_valid(volume, 8)", TsFunc::CountValid, "volume"),
        ] {
            assert_eq!(
                parse(src),
                Ok(ts(func, vec![fld_arg(field)], window_of(src))),
                "parse {}",
                src
            );
        }

        // Two-series regression family.
        for (src, func) in [
            ("ts_regression_resid(y, x, 30)", TsFunc::RegressionResid),
            ("ts_regression_beta(y, x, 30)", TsFunc::RegressionBeta),
            ("ts_covariance(y, x, 45)", TsFunc::Covariance),
        ] {
            assert_eq!(
                parse(src),
                Ok(ts(func, vec![fld_arg("y"), fld_arg("x")], window_of(src))),
                "parse {}",
                src
            );
        }

        // ts_quantile carries a scalar level parameter between args and
        // window; ts_scale's target lives on cs_scale.
        assert_eq!(
            parse("ts_quantile(close, 0.75, 20)"),
            Ok(ts_param(TsFunc::Quantile, vec![fld_arg("close")], 0.75, 20))
        );
    }

    /// Extract the trailing window integer used in `new_windowed_operators_parse_with_arity_and_param`.
    fn window_of(src: &str) -> usize {
        let inside = &src[..src.len() - 1];
        inside
            .rsplit(',')
            .next()
            .expect("window present")
            .trim()
            .parse()
            .expect("integer window")
    }

    #[test]
    fn cross_sectional_operators_parse_without_window() {
        for (src, func) in [
            ("cs_rank(close)", TsFunc::CsRank),
            ("cs_zscore(close)", TsFunc::CsZscore),
            ("cs_demean(close)", TsFunc::CsDemean),
            ("abs(close)", TsFunc::Abs),
            ("log(close)", TsFunc::Log),
            ("sign(ret)", TsFunc::Sign),
        ] {
            let field = if src == "sign(ret)" { "ret" } else { "close" };
            assert_eq!(
                parse(src),
                Ok(ts(func, vec![fld_arg(field)], 0)),
                "parse {}",
                src
            );
        }
        assert_eq!(
            parse("cs_scale(close, 2.5)"),
            Ok(ts_param(TsFunc::CsScale, vec![fld_arg("close")], 2.5, 0))
        );
        assert_eq!(
            parse("elem_max(close, volume)"),
            Ok(ts(
                TsFunc::ElemMax,
                vec![fld_arg("close"), fld_arg("volume")],
                0
            ))
        );
        assert_eq!(
            parse("if_else(ret, close/open, close*volume)"),
            Ok(ts(
                TsFunc::IfElse,
                vec![
                    fld_arg("ret"),
                    TsArg::Expr(Box::new(bin(BinOp::Div, f("close"), f("open")))),
                    TsArg::Expr(Box::new(bin(BinOp::Mul, f("close"), f("volume")))),
                ],
                0
            ))
        );
        // Cross-sectional functions nest like any other expression.
        assert!(parse("cs_rank(ts_mean(close, 5))").is_ok());
    }

    #[test]
    fn name_from_name_arity_and_windowed_tables_stay_consistent() {
        let all = [
            TsFunc::Mean,
            TsFunc::Std,
            TsFunc::Delta,
            TsFunc::Delay,
            TsFunc::Sum,
            TsFunc::Rank,
            TsFunc::Corr,
            TsFunc::Zscore,
            TsFunc::Ewma,
            TsFunc::Min,
            TsFunc::Max,
            TsFunc::Median,
            TsFunc::Quantile,
            TsFunc::Skewness,
            TsFunc::Kurtosis,
            TsFunc::Ir,
            TsFunc::Product,
            TsFunc::ArgMax,
            TsFunc::ArgMin,
            TsFunc::MaxDiff,
            TsFunc::MinDiff,
            TsFunc::Scale,
            TsFunc::QuantilePos,
            TsFunc::DecayLinear,
            TsFunc::RegressionResid,
            TsFunc::RegressionBeta,
            TsFunc::Covariance,
            TsFunc::Returns,
            TsFunc::SignDelta,
            TsFunc::TrendSlope,
            TsFunc::Backfill,
            TsFunc::CountValid,
            TsFunc::CsRank,
            TsFunc::CsZscore,
            TsFunc::CsScale,
            TsFunc::CsDemean,
            TsFunc::Abs,
            TsFunc::Log,
            TsFunc::Sign,
            TsFunc::ElemMax,
            TsFunc::ElemMin,
            TsFunc::IfElse,
        ];
        // 9 original + 33 new operators.
        assert_eq!(all.len(), 42);
        for func in all {
            assert_eq!(
                TsFunc::from_name(func.name()),
                Some(func),
                "name/from_name mismatch for {}",
                func.name()
            );
        }
        // Only these two carry scalar parameters.
        assert!(TsFunc::Quantile.scalar_param().is_some());
        assert!(TsFunc::CsScale.scalar_param().is_some());
        assert_eq!(all.iter().filter(|f| f.scalar_param().is_some()).count(), 2);
        // Window classification spot checks.
        assert!(TsFunc::Ewma.windowed());
        assert!(!TsFunc::CsRank.windowed());
        assert!(!TsFunc::IfElse.windowed());
        // Arity table spot checks.
        assert_eq!(TsFunc::Corr.arity(), 2);
        assert_eq!(TsFunc::Covariance.arity(), 2);
        assert_eq!(TsFunc::ElemMin.arity(), 2);
        assert_eq!(TsFunc::IfElse.arity(), 3);
        assert_eq!(TsFunc::Quantile.arity(), 1);
        assert_eq!(TsFunc::Backfill.arity(), 1);
    }

    #[test]
    fn window_accepts_integral_floats_numbers_accept_scientific_notation() {
        assert_eq!(
            parse("ts_sum(close, 5.0)"),
            Ok(ts(TsFunc::Sum, vec![fld_arg("close")], 5))
        );
        assert_eq!(
            parse("close*1e3"),
            Ok(bin(BinOp::Mul, f("close"), num(1000.0)))
        );
        assert_eq!(
            parse("2.5e-1+ret"),
            Ok(bin(BinOp::Add, num(0.25), f("ret")))
        );
    }

    #[test]
    fn error_cases_report_position_and_kind() {
        assert!(matches!(
            parse("foo(close, 5)"),
            Err(ParseError::UnknownFunction { .. })
        ));
        assert!(matches!(
            parse("ts_mean(close, ret)"),
            Err(ParseError::InvalidWindow { .. })
        ));
        assert!(matches!(
            parse("ts_mean(close, 0)"),
            Err(ParseError::InvalidWindow { .. })
        ));
        assert!(matches!(
            parse("ts_mean(close, -5)"),
            Err(ParseError::InvalidWindow { .. })
        ));
        assert!(matches!(
            parse("ts_mean()"),
            Err(ParseError::MissingArguments { .. })
        ));
        assert!(matches!(
            parse("ts_corr(close, 5)"),
            Err(ParseError::WrongArity { .. })
        ));
        assert!(matches!(
            parse("ts_corr(close, open, volume, 5)"),
            Err(ParseError::WrongArity { .. })
        ));
        // Input ends while ',' or ')' is still expected.
        assert!(matches!(
            parse("ts_mean(close, 5"),
            Err(ParseError::UnexpectedEof)
        ));
        assert!(matches!(
            parse("ts_mean(close 5)"),
            Err(ParseError::UnexpectedToken { .. })
        ));
        assert!(matches!(parse(""), Err(ParseError::UnexpectedEof)));
        assert!(matches!(parse("close+"), Err(ParseError::UnexpectedEof)));
        assert!(matches!(
            parse("close close"),
            Err(ParseError::TrailingInput { .. })
        ));
        assert!(matches!(
            parse("close @ open"),
            Err(ParseError::UnknownSymbol { .. })
        ));
        assert!(matches!(
            parse("1.2.3"),
            Err(ParseError::UnknownSymbol { .. })
        ));
        assert!(matches!(
            parse("1e"),
            Err(ParseError::MalformedNumber { .. })
        ));

        // Display renders human-readable messages.
        let msg = parse("foo(x, 5)").unwrap_err().to_string();
        assert!(msg.contains("unknown function 'foo'"));
    }

    #[test]
    fn new_operator_error_cases() {
        // Windowed operators reject a missing or non-integer window: the
        // only series argument is consumed by the window slot.
        assert!(matches!(
            parse("ts_min(close)"),
            Err(ParseError::InvalidWindow { .. })
        ));
        assert!(matches!(
            parse("ts_min(close, 0)"),
            Err(ParseError::InvalidWindow { .. })
        ));
        // Cross-sectional operators reject a trailing window argument.
        assert!(matches!(
            parse("cs_rank(close, 5)"),
            Err(ParseError::WrongArity { .. })
        ));
        assert!(matches!(
            parse("if_else(a, b)"),
            Err(ParseError::WrongArity { .. })
        ));
        assert!(matches!(
            parse("elem_max(a, b, c)"),
            Err(ParseError::WrongArity { .. })
        ));
        // Scalar parameters must be numeric literals in range.
        assert!(matches!(
            parse("ts_quantile(close, ret, 10)"),
            Err(ParseError::InvalidParam { .. })
        ));
        assert!(matches!(
            parse("ts_quantile(close, 1.5, 10)"),
            Err(ParseError::InvalidParam { .. })
        ));
        assert!(matches!(
            parse("ts_quantile(close, -0.1, 10)"),
            Err(ParseError::InvalidParam { .. })
        ));
        // A windowed call that is one argument short leaves nothing for the
        // scalar parameter slot.
        assert!(matches!(
            parse("ts_quantile(close, 10)"),
            Err(ParseError::InvalidParam { .. })
        ));
        assert!(matches!(
            parse("cs_scale(close, volume)"),
            Err(ParseError::InvalidParam { .. })
        ));
        assert!(matches!(
            parse("cs_scale(close)"),
            Err(ParseError::InvalidParam { .. })
        ));

        // Display renders human-readable messages.
        let msg = parse("ts_quantile(close, 2.0, 5)").unwrap_err().to_string();
        assert!(msg.contains("quantile level"));
    }

    #[test]
    fn display_round_trip_preserves_structure() {
        let cases = [
            "close",
            "42",
            "-close",
            "-(close+open)",
            "--ret",
            "-3.5",
            "close+open*volume",
            "(close-open)/volume",
            "a-(b-c)",
            "a/(b*c)",
            "(a+b)*(c-d)",
            "ts_mean(close, 20)",
            "ts_corr(close, volume, 60)",
            "ts_rank(close/open, 12)",
            "ts_zscore(ts_mean(close, 8), 480)",
            "-ts_delta(close, 1)*volume+ts_rank(ret, 20)",
            // New operator families.
            "ts_min(ts_max(close, 5), 10)",
            "ts_argmax(close/volume, 30)-ts_argmin(close, 30)",
            "ts_quantile(close, 0.25, 20)",
            "cs_scale(close, 2.5)",
            "ts_regression_resid(y, ts_delay(x, 1), 60)",
            "if_else(ret, close/open, close*volume)",
            "cs_rank(cs_zscore(ret))*ts_decay_linear(volume, 8)",
        ];
        for src in cases {
            let ast = parse(src).unwrap_or_else(|e| panic!("'{}' failed: {}", src, e));
            let printed = ast.to_string();
            let reparsed =
                parse(&printed).unwrap_or_else(|e| panic!("re-parse '{}' failed: {}", printed, e));
            assert_eq!(ast, reparsed, "round trip mismatch for '{}'", src);
        }
    }

    #[test]
    fn collect_fields_unique_in_first_appearance_order() {
        let ast = parse("ts_corr(close/volume, close, 30)+open*volume-ret").expect("valid");
        assert_eq!(
            collect_fields(&ast),
            vec![
                "close".to_string(),
                "volume".to_string(),
                "open".to_string(),
                "ret".to_string()
            ]
        );
        assert!(collect_fields(&AstNode::Number(1.0)).is_empty());
    }

    #[test]
    fn hash_ast_equal_for_identical_structures_only() {
        let a = parse("ts_mean(close, 20)").expect("valid");
        let b = AstNode::TsFunc {
            func: TsFunc::Mean,
            args: vec![fld_arg("close")],
            window: 20,
            param: 0.0,
        };
        assert_eq!(hash_ast(&a), hash_ast(&b));

        assert_ne!(
            hash_ast(&a),
            hash_ast(&parse("ts_mean(close, 21)").unwrap())
        );
        assert_ne!(hash_ast(&a), hash_ast(&parse("ts_mean(open, 20)").unwrap()));
        assert_ne!(hash_ast(&a), hash_ast(&parse("ts_sum(close, 20)").unwrap()));
        // The scalar parameter is part of operator identity.
        assert_ne!(
            hash_ast(&parse("ts_quantile(close, 0.25, 10)").unwrap()),
            hash_ast(&parse("ts_quantile(close, 0.75, 10)").unwrap())
        );
        assert_ne!(
            hash_ast(&parse("close+open").unwrap()),
            hash_ast(&parse("open+close").unwrap())
        );

        // 0.0 and -0.0 compare equal, so they must hash identically.
        assert_eq!(hash_ast(&num(0.0)), hash_ast(&AstNode::Number(-0.0)));

        // Hash is stable across repeated calls and independent of context.
        assert_eq!(hash_ast(&a), hash_ast(&a.clone()));
    }
}
