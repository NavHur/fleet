//! Modifier lists PHP refuses while parsing, with a CompileError that TOKEN_PARSE raises: a repeated
//! modifier, two visibilities, `abstract` with `final`, and modifiers a declaration cannot take.

use mago_syntax::cst::cst::Modifier;
use mago_syntax::cst::sequence::Sequence;

/// What a modifier list belongs to.
#[derive(Clone, Copy)]
pub enum Target {
    Class,
    AnonymousClass,
    Method,
    Constant,
    Property,
    Parameter,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Static,
    Final,
    Abstract,
    Readonly,
    Visibility(u8),
    SetVisibility(u8),
}

fn kind(modifier: &Modifier) -> Kind {
    match modifier {
        Modifier::Static(_) => Kind::Static,
        Modifier::Final(_) => Kind::Final,
        Modifier::Abstract(_) => Kind::Abstract,
        Modifier::Readonly(_) => Kind::Readonly,
        Modifier::Public(_) => Kind::Visibility(0),
        Modifier::Protected(_) => Kind::Visibility(1),
        Modifier::Private(_) => Kind::Visibility(2),
        Modifier::PublicSet(_) => Kind::SetVisibility(0),
        Modifier::ProtectedSet(_) => Kind::SetVisibility(1),
        Modifier::PrivateSet(_) => Kind::SetVisibility(2),
    }
}

/// Whether PHP rejects `modifiers` on `target`.
pub fn invalid(modifiers: &Sequence<Modifier>, target: Target) -> bool {
    let kinds: Vec<Kind> = modifiers.iter().map(kind).collect();
    let repeated = kinds
        .iter()
        .enumerate()
        .any(|(index, kind)| kinds[..index].contains(kind));
    let count = |wanted: fn(&Kind) -> bool| kinds.iter().filter(|kind| wanted(kind)).count();
    let visibilities = count(|kind| matches!(kind, Kind::Visibility(_)));
    let set_visibilities = count(|kind| matches!(kind, Kind::SetVisibility(_)));
    let abstract_final = kinds.contains(&Kind::Abstract) && kinds.contains(&Kind::Final);
    repeated
        || visibilities > 1
        || set_visibilities > 1
        || abstract_final
        || kinds.iter().any(|&kind| refused(target, kind))
}

/// A modifier `target` cannot take at all.
fn refused(target: Target, kind: Kind) -> bool {
    match target {
        Target::Property => false,
        Target::Class => !matches!(kind, Kind::Final | Kind::Abstract | Kind::Readonly),
        Target::AnonymousClass => kind != Kind::Readonly,
        Target::Method => matches!(kind, Kind::Readonly | Kind::SetVisibility(_)),
        Target::Constant => matches!(
            kind,
            Kind::Static | Kind::Abstract | Kind::Readonly | Kind::SetVisibility(_)
        ),
        Target::Parameter => matches!(kind, Kind::Static | Kind::Abstract),
    }
}
