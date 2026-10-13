#!/usr/bin/perl
# Read configuration through the installed SmokePing parser; never run probes.
use strict;
use warnings;
# SmokePing's probe base adds ".." to @INC. Resolve it from a public, fixed
# directory before loading SmokePing or any probes, even when invoked manually.
BEGIN { chdir '/' or die "Cannot enter renderer working directory: $!\n"; }
use lib '/usr/share/perl5', '/usr/share/smokeping/lib';
use Smokeping;
use JSON::PP;
$Smokeping::cgimode = 1;
my $cfg = Smokeping::get_config(Smokeping::get_parser(), $ARGV[0] || '/etc/smokeping/config');
my $probes = Smokeping::load_probes($cfg);
my %targets;
sub visit {
    my ($tree, $path, $hidden) = @_;
    $hidden ||= ($tree->{hide} || '') eq 'yes';
    if (!$hidden && $tree->{host} && $tree->{host} !~ m{^/} && @$path) {
        my $probe = $probes->{$tree->{probe}};
        if ($probe) {
            my $target = join '.', @$path;
            my $entry = { file => join('/', @$path).'.rrd', pings => 0+$probe->_pings($tree),
                step => 0+$probe->step(), unit => $probe->ProbeUnit(),
                title => $tree->{title} || $tree->{menu} || $target,
                loss_colors => $cfg->{Presentation}{detail}{loss_colors}{_table} };
            $targets{$target} = $entry unless ($tree->{nomasterpoll} || '') eq 'yes';
            for my $slave (split /\s+/, $tree->{slaves} || '') {
                next unless exists $cfg->{Slaves}{$slave};
                $targets{"$target~$slave"} = { %$entry, file => join('/', @$path)."~$slave.rrd",
                    title => "$entry->{title} from ".($cfg->{Slaves}{$slave}{display_name} || $slave) };
            }
        }
    }
    for my $key (sort keys %$tree) {
        next if $key =~ /^__/ || ref($tree->{$key}) ne 'HASH';
        visit($tree->{$key}, [@$path, $key], $hidden);
    }
}
visit($cfg->{Targets}, [], 0);
print JSON::PP->new->canonical->encode({ datadir => $cfg->{General}{datadir},
    overview_range => Smokeping::exp2seconds($cfg->{Presentation}{overview}{range}), targets => \%targets });
