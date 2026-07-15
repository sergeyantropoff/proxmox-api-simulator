#!/usr/bin/env perl
use strict;
use warnings;
use HTTP::Tiny;
use JSON qw(decode_json encode_json);

sub uri_escape {
    my ($value) = @_;
    $value =~ s/([^A-Za-z0-9\-\._~])/sprintf('%%%02X', ord($1))/eg;
    return $value;
}

my $base  = $ENV{PVE_BASE}  // 'http://localhost:8006/api2/json';
my $node  = $ENV{PVE_NODE}  // 'pve01';
my $vmid  = $ENV{PVE_VMID}  // '115';
my $token = $ENV{PVE_API_TOKEN} // 'root@pam!automation=automation-secret';
my $auth  = "PVEAPIToken=$token";
my $http  = HTTP::Tiny->new(timeout => 60);

sub api {
    my ($method, $path, $body) = @_;
    my %opts = (headers => { Authorization => $auth });
    if (defined $body) {
        $opts{headers}{'Content-Type'} = 'application/x-www-form-urlencoded';
        $opts{content} = $body;
    }
    my $res = $http->request($method, "$base$path", \%opts);
    die "$method $path failed: $res->{status} $res->{content}\n" unless $res->{success};
    my $json = decode_json($res->{content});
    return $json->{data};
}

sub wait_task {
    my ($upid) = @_;
    my $deadline = time + 120;
    while (time < $deadline) {
        my $status = api('GET', "/nodes/$node/tasks/" . uri_escape($upid) . '/status');
        return if ref $status eq 'HASH' && ($status->{status} // '') eq 'stopped';
        select(undef, undef, undef, 0.5);
    }
    die "timeout waiting for $upid\n";
}

print "version: ", encode_json(api('GET', '/version')), "\n";
my $upid = api('POST', "/nodes/$node/qemu", "vmid=$vmid&name=perl-$vmid&cores=1&memory=512");
wait_task($upid);
$upid = api('POST', "/nodes/$node/qemu/$vmid/status/start");
wait_task($upid);
print "status: ", encode_json(api('GET', "/nodes/$node/qemu/$vmid/status/current")), "\n";
$upid = api('POST', "/nodes/$node/qemu/$vmid/status/stop");
wait_task($upid);
$upid = api('DELETE', "/nodes/$node/qemu/$vmid");
wait_task($upid);
print "ok\n";
