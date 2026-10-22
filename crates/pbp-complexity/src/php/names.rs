//! PHP's token names for mago's token kinds, as `PhpToken::getTokenName()` reports them.
//!
//! Single-character tokens are named by their character. A few kinds depend on context that mago's lexer
//! leaves to its parser (keywords used as names, `&` before a variable, braces inside strings); tokens.rs
//! settles those after this context-free lookup.

use mago_syntax::token::{DocumentKind, TokenKind as K};

/// The PHP name of `kind` outside any special context; `None` for whitespace and comments.
pub fn name(kind: K) -> Option<&'static str> {
    Some(match kind {
        K::Whitespace
        | K::SingleLineComment
        | K::HashComment
        | K::MultiLineComment
        | K::DocBlockComment
        | K::OpenTag
        | K::ShortOpenTag => return None,
        _ => punctuation(kind)
            .or_else(|| operator(kind))
            .or_else(|| literal(kind))
            .or_else(|| keyword(kind))
            .or_else(|| declaration(kind))
            .unwrap_or("T_STRING"),
    })
}

fn punctuation(kind: K) -> Option<&'static str> {
    Some(match kind {
        K::Ampersand => "T_AMPERSAND_NOT_FOLLOWED_BY_VAR_OR_VARARG",
        K::At => "@",
        K::Asterisk => "*",
        K::Bang => "!",
        K::Caret => "^",
        K::Colon => ":",
        K::Comma => ",",
        K::Dollar => "$",
        K::Dot => ".",
        K::DoubleQuote => "\"",
        K::Backtick => "`",
        K::Equal => "=",
        K::GreaterThan => ">",
        K::LessThan => "<",
        K::LeftBrace => "{",
        K::RightBrace => "}",
        K::LeftBracket => "[",
        K::RightBracket => "]",
        K::LeftParenthesis => "(",
        K::RightParenthesis => ")",
        K::Minus => "-",
        K::Percent => "%",
        K::Pipe => "|",
        K::Plus => "+",
        K::Question => "?",
        K::Semicolon => ";",
        K::Slash => "/",
        K::Tilde => "~",
        _ => return None,
    })
}

fn operator(kind: K) -> Option<&'static str> {
    Some(match kind {
        K::AmpersandEqual => "T_AND_EQUAL",
        K::AmpersandAmpersand => "T_BOOLEAN_AND",
        K::PipePipe => "T_BOOLEAN_OR",
        K::And => "T_LOGICAL_AND",
        K::Or => "T_LOGICAL_OR",
        K::Xor => "T_LOGICAL_XOR",
        K::MinusGreaterThan => "T_OBJECT_OPERATOR",
        K::QuestionMinusGreaterThan => "T_NULLSAFE_OBJECT_OPERATOR",
        K::ColonColon => "T_DOUBLE_COLON",
        K::EqualGreaterThan => "T_DOUBLE_ARROW",
        K::QuestionQuestion => "T_COALESCE",
        K::QuestionQuestionEqual => "T_COALESCE_EQUAL",
        K::BangEqual | K::LessThanGreaterThan => "T_IS_NOT_EQUAL",
        K::BangEqualEqual => "T_IS_NOT_IDENTICAL",
        K::EqualEqual => "T_IS_EQUAL",
        K::EqualEqualEqual => "T_IS_IDENTICAL",
        K::LessThanEqualGreaterThan => "T_SPACESHIP",
        K::GreaterThanEqual => "T_IS_GREATER_OR_EQUAL",
        K::LessThanEqual => "T_IS_SMALLER_OR_EQUAL",
        K::CaretEqual => "T_XOR_EQUAL",
        K::MinusEqual => "T_MINUS_EQUAL",
        K::PlusEqual => "T_PLUS_EQUAL",
        K::AsteriskEqual => "T_MUL_EQUAL",
        K::SlashEqual => "T_DIV_EQUAL",
        K::DotEqual => "T_CONCAT_EQUAL",
        K::PercentEqual => "T_MOD_EQUAL",
        K::PipeEqual => "T_OR_EQUAL",
        K::AsteriskAsterisk => "T_POW",
        K::AsteriskAsteriskEqual => "T_POW_EQUAL",
        K::LeftShift => "T_SL",
        K::LeftShiftEqual => "T_SL_EQUAL",
        K::RightShift => "T_SR",
        K::RightShiftEqual => "T_SR_EQUAL",
        K::PlusPlus => "T_INC",
        K::MinusMinus => "T_DEC",
        K::DotDotDot => "T_ELLIPSIS",
        K::NamespaceSeparator => "T_NS_SEPARATOR",
        K::HashLeftBracket => "T_ATTRIBUTE",
        K::PipeGreaterThan => "T_PIPE",
        K::CloseTag => "T_CLOSE_TAG",
        K::EchoTag => "T_OPEN_TAG_WITH_ECHO",
        _ => return cast(kind),
    })
}

fn cast(kind: K) -> Option<&'static str> {
    Some(match kind {
        K::ArrayCast => "T_ARRAY_CAST",
        K::BoolCast | K::BooleanCast => "T_BOOL_CAST",
        K::DoubleCast | K::RealCast | K::FloatCast => "T_DOUBLE_CAST",
        K::IntCast | K::IntegerCast => "T_INT_CAST",
        K::ObjectCast => "T_OBJECT_CAST",
        K::UnsetCast => "T_UNSET_CAST",
        K::StringCast | K::BinaryCast => "T_STRING_CAST",
        K::VoidCast => "T_VOID_CAST",
        _ => return None,
    })
}

fn literal(kind: K) -> Option<&'static str> {
    Some(match kind {
        K::Variable => "T_VARIABLE",
        K::LiteralInteger => "T_LNUMBER",
        K::LiteralFloat => "T_DNUMBER",
        K::LiteralString | K::PartialLiteralString => "T_CONSTANT_ENCAPSED_STRING",
        K::StringPart => "T_ENCAPSED_AND_WHITESPACE",
        K::StringVariableName => "T_STRING_VARNAME",
        K::OffsetNumber => "T_NUM_STRING",
        K::DocumentStart(DocumentKind::Heredoc | DocumentKind::Nowdoc) => "T_START_HEREDOC",
        K::DocumentEnd => "T_END_HEREDOC",
        K::DollarLeftBrace => "T_DOLLAR_OPEN_CURLY_BRACES",
        K::InlineText | K::InlineShebang => "T_INLINE_HTML",
        K::QualifiedIdentifier => "T_NAME_QUALIFIED",
        K::FullyQualifiedIdentifier => "T_NAME_FULLY_QUALIFIED",
        K::ClassConstant => "T_CLASS_C",
        K::TraitConstant => "T_TRAIT_C",
        K::FunctionConstant => "T_FUNC_C",
        K::MethodConstant => "T_METHOD_C",
        K::LineConstant => "T_LINE",
        K::FileConstant => "T_FILE",
        K::DirConstant => "T_DIR",
        K::NamespaceConstant => "T_NS_C",
        K::PropertyConstant => "T_PROPERTY_C",
        _ => return None,
    })
}

fn keyword(kind: K) -> Option<&'static str> {
    Some(match kind {
        K::Eval => "T_EVAL",
        K::Die | K::Exit => "T_EXIT",
        K::Print => "T_PRINT",
        K::Echo => "T_ECHO",
        K::Array => "T_ARRAY",
        K::As => "T_AS",
        K::Break => "T_BREAK",
        K::Continue => "T_CONTINUE",
        K::Case => "T_CASE",
        K::Default => "T_DEFAULT",
        K::Catch => "T_CATCH",
        K::Finally => "T_FINALLY",
        K::Try => "T_TRY",
        K::Throw => "T_THROW",
        K::Clone => "T_CLONE",
        K::Declare => "T_DECLARE",
        K::Do => "T_DO",
        K::While => "T_WHILE",
        K::For => "T_FOR",
        K::Foreach => "T_FOREACH",
        K::If => "T_IF",
        K::Else => "T_ELSE",
        K::ElseIf => "T_ELSEIF",
        K::EndDeclare => "T_ENDDECLARE",
        K::EndFor => "T_ENDFOR",
        K::EndForeach => "T_ENDFOREACH",
        K::EndIf => "T_ENDIF",
        K::EndSwitch => "T_ENDSWITCH",
        K::EndWhile => "T_ENDWHILE",
        K::Switch => "T_SWITCH",
        K::Match => "T_MATCH",
        K::Empty => "T_EMPTY",
        K::Isset => "T_ISSET",
        K::Unset => "T_UNSET",
        K::List => "T_LIST",
        K::Global => "T_GLOBAL",
        K::Goto => "T_GOTO",
        K::Include => "T_INCLUDE",
        K::IncludeOnce => "T_INCLUDE_ONCE",
        K::Require => "T_REQUIRE",
        K::RequireOnce => "T_REQUIRE_ONCE",
        K::Instanceof => "T_INSTANCEOF",
        K::Insteadof => "T_INSTEADOF",
        K::New => "T_NEW",
        K::Return => "T_RETURN",
        K::Yield => "T_YIELD",
        K::HaltCompiler => "T_HALT_COMPILER",
        _ => return None,
    })
}

fn declaration(kind: K) -> Option<&'static str> {
    Some(match kind {
        K::Abstract => "T_ABSTRACT",
        K::Final => "T_FINAL",
        K::Readonly => "T_READONLY",
        K::Static => "T_STATIC",
        K::Var => "T_VAR",
        K::Public => "T_PUBLIC",
        K::Protected => "T_PROTECTED",
        K::Private => "T_PRIVATE",
        K::PublicSet => "T_PUBLIC_SET",
        K::ProtectedSet => "T_PROTECTED_SET",
        K::PrivateSet => "T_PRIVATE_SET",
        K::Class => "T_CLASS",
        K::Interface => "T_INTERFACE",
        K::Trait => "T_TRAIT",
        K::Enum => "T_ENUM",
        K::Extends => "T_EXTENDS",
        K::Implements => "T_IMPLEMENTS",
        K::Function => "T_FUNCTION",
        K::Fn => "T_FN",
        K::Const => "T_CONST",
        K::Use => "T_USE",
        K::Namespace => "T_NAMESPACE",
        K::Callable => "T_CALLABLE",
        _ => return None,
    })
}
